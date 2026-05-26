\documentclass[conference]{IEEEtran}
\usepackage{amsmath,amssymb,amsthm}
\usepackage{booktabs}
\usepackage{url}
\usepackage{hyperref}

\newtheorem{definition}{Definition}
\newtheorem{proposition}{Proposition}
\newtheorem{theorem}{Theorem}

\begin{document}

\title{Drift-Aware Attestation: A Portable Epistemic Substrate\\
for Non-Stationary Autonomous Systems}

\author{\IEEEauthorblockN{A. Khaalis Wooden, Sr.}
\IEEEauthorblockA{Zuup Innovation Lab / Visionblox LLC\\
MSIT Candidate, Southern New Hampshire University\\
Email: aldrich.wooden@snhu.edu}}

\maketitle

\begin{abstract}
Autonomous systems increasingly compose outputs across heterogeneous layers---
perception, representation, spatial mapping, and policy---and increasingly act
on those outputs without a human in the loop. Two failure modes recur across
every such stack: (i) provenance and calibrated confidence are stripped as data
moves up the layers, so an actor cannot tell how trustworthy a derived artifact
is or where it came from; and (ii) artifacts silently retain validity after the
input distribution that justified them has drifted. We present the
\emph{Drift-Aware Claim} (DAC), a signed, hash-chained envelope that wraps every
inter-layer artifact with its provenance graph, a conformal confidence with a
coverage guarantee, a data classification, and a validity window. A runtime
enforces \emph{monotone propagation}: a derived claim inherits the weakest
confidence, the highest sensitivity, the shortest validity, and any human-gate
requirement of its inputs, as a typed precondition of derivation. A drift
monitor cascades invalidation through the provenance graph the moment a governing
input shifts. We give the lattice semantics of propagation, prove closure
properties, and report a reference implementation built entirely from
open-source components (Ed25519, SQLite, NumPy/SciPy). Across seven falsifiable
acceptance properties the substrate behaves as specified; notably, under a
$3\times$ scale shift, static conformal coverage collapses to $0.40$ while the
adaptive variant holds $0.90$, demonstrating confidence that reacts to drift
rather than silently misleading.
\end{abstract}

\begin{IEEEkeywords}
conformal prediction, concept drift, provenance, attestation, compliance,
non-stationarity, AI safety.
\end{IEEEkeywords}

\section{Introduction}
The next generation of AI form factors---wearable assistants, embodied robots,
and delegated software agents---are not monolithic models but \emph{stacks}: a
sensor produces a reading, an encoder produces an embedding, a mapper produces a
spatial estimate, and a policy produces an action. Two properties that any
acting system needs---knowing \emph{where} an artifact came from and \emph{how
much} to trust it---are routinely lost at each layer boundary. Audit logs live
in one subsystem, an uncalibrated softmax in another, and an ad-hoc
time-to-live in a third; none of them compose. Independently, the inputs that
justified an artifact drift over time, yet the artifact's apparent validity does
not decay, a hazard long studied under concept drift and dataset
shift~\cite{gama2014survey,ditzler2015nonstationary,quinonero2009dataset} and
recognized as a source of hidden technical debt in deployed
systems~\cite{sculley2015debt}.

We argue these are one problem and build one substrate for it. Our
contributions are: (1) the \emph{Drift-Aware Claim} (DAC), a portable
attestation envelope that carries provenance, calibrated confidence, validity,
and classification across layer boundaries (\S\ref{sec:dac}); (2) a
\emph{monotone propagation} contract with lattice semantics and closure proofs
that make confidence/sensitivity/validity impossible to silently drop under
derivation (\S\ref{sec:prop}); (3) a coupling of \emph{adaptive conformal
inference} to a \emph{drift monitor} so that confidence and validity react to
non-stationarity (\S\ref{sec:conf}, \S\ref{sec:drift}); and (4) an open-source,
zero-budget reference implementation with an OSCAL compliance export, evaluated
on seven falsifiable properties (\S\ref{sec:impl}, \S\ref{sec:eval}).

\section{Related Work}
\textbf{Calibrated uncertainty.} Conformal prediction provides distribution-free,
finite-sample coverage under exchangeability~\cite{vovk2005algorithmic,
shafer2008tutorial,angelopoulos2023gentle}, with extensions for covariate
shift~\cite{tibshirani2019covariate}, quantile regression~\cite{romano2019cqr},
and, crucially for us, the non-exchangeable / drifting
regime~\cite{gibbs2021adaptive,barber2023beyond}. We use split conformal for the
stationary case and Adaptive Conformal Inference (ACI)~\cite{gibbs2021adaptive}
to maintain coverage under drift.
\textbf{Drift detection.} Sequential change detection dates to the
Page--Hinkley test~\cite{page1954continuous}; modern detectors include adaptive
windowing~\cite{bifet2007adwin} and distributional two-sample tests such as
Kolmogorov--Smirnov~\cite{massey1951ks}. Surveys~\cite{gama2014survey} catalog
the space. Prior work \emph{detects} drift; we additionally bind detection to a
\emph{validity semantics} over a provenance graph.
\textbf{Provenance and attestation.} The W3C PROV data model~\cite{prov2013}
formalizes provenance; content provenance standards~\cite{c2pa} attest media
origin; secure audit logs use hash chaining~\cite{schneier1999audit,
merkle1987digital} and signatures~\cite{bernstein2012ed25519}. Compliance
tooling such as OSCAL~\cite{nist_oscal} consumes assessment evidence against
controls~\cite{nist80053}. We unify these into a single per-artifact envelope
and add the drift dimension that none of them carry, motivated by the safety of
delegated action~\cite{amodei2016concrete}.

\section{The Drift-Aware Claim}\label{sec:dac}
\begin{definition}[DAC]
A Drift-Aware Claim is a tuple
$c=\langle \mathrm{id}, k, h, \pi, P, \kappa, \mathcal{V}, \ell, g, \sigma, \rho\rangle$
where $k$ is the artifact kind; $h$ is a cryptographic hash of the artifact
payload; $\pi$ is the producer identity (an Ed25519 public key); $P$ is the set
of parent claim identifiers (edges of a provenance DAG); $\kappa\in[0,1]$ is a
calibrated confidence (a coverage level) with an optional prediction interval;
$\mathcal{V}=\langle t_0,t_1,s\rangle$ is a validity window with status
$s\in\{\textsc{valid},\textsc{stale},\textsc{revoked}\}$ governed by a monitor
identifier; $\ell\in L$ is a data classification in the sensitivity lattice
$L=\textsc{public}<\textsc{internal}<\textsc{confidential}<\textsc{regulated}$;
$g\in\{0,1\}$ is a human-in-the-loop requirement; $\sigma$ is the producer's
signature over the semantic fields; and $\rho$ is the hash-chain link to the
prior record.
\end{definition}
The artifact itself is never relocated---the DAC carries only its hash---so the
envelope is a lightweight metadata object that can travel and be stored
independently of (potentially large or regulated) payloads.

\section{Monotone Propagation}\label{sec:prop}
Let a derived claim $c$ be produced from parents $P=\{p_1,\dots,p_n\}$ together
with the producer's locally asserted values. The runtime computes the derived
fields by the operators in Table~\ref{tab:prop}.

\begin{table}[t]\centering
\caption{Propagation operators at a derivation.}\label{tab:prop}
\begin{tabular}{@{}lll@{}}
\toprule
Field & Operator & Lattice role\\
\midrule
Confidence $\kappa$ & $\min$ over $\{\kappa_{\text{self}}\}\cup\{\kappa_{p_i}\}$ & meet on $([0,1],\le)$\\
Classification $\ell$ & $\max$ over self and parents & join on $L$\\
Validity $\mathcal{V}$ & interval intersection & meet on intervals\\
HITL $g$ & logical \textsc{or}; forced if \textsc{regulated} & join on $\{0,1\}$\\
Status $s$ & \textsc{stale} if any parent $\ne$ \textsc{valid} & absorbing\\
\bottomrule
\end{tabular}
\end{table}

\begin{proposition}[Confidence is non-increasing along provenance]
For any directed path $p\rightarrow\cdots\rightarrow c$ in the provenance DAG,
$\kappa_c\le\kappa_p$.
\end{proposition}
\begin{proof}
At each derivation $\kappa_c=\min(\kappa_{\text{self}},\min_i\kappa_{p_i})\le
\kappa_{p_j}$ for every parent $p_j$. The path claim follows by induction on path
length.
\end{proof}

\begin{proposition}[No declassification by derivation]
Sensitivity is non-decreasing along provenance: $\ell_c\ge\ell_p$ for any
ancestor $p$ of $c$.
\end{proposition}
\begin{proof}
$\ell_c=\max(\ell_{\text{self}},\max_i\ell_{p_i})\ge\ell_{p_j}$ at each step;
induct on path length. Consequently a \textsc{regulated} input forces
$\ell_c=\textsc{regulated}$ and, by the HITL rule, $g_c=1$.
\end{proof}

\begin{theorem}[Soundness of drift cascade]\label{thm:cascade}
Let monitor $m$ govern a set $S_m$ of claims. After invalidation triggered by
$m$, every claim reachable from $S_m$ along provenance edges has status
\textsc{stale}.
\end{theorem}
\begin{proof}
Invalidation performs a breadth-first traversal of child edges from the seeds
$S_m$, setting each visited \textsc{valid} claim to \textsc{stale}; the visited
set is exactly the set of nodes reachable from $S_m$, i.e.\ the transitive
closure of the child relation. Combined with the status rule of
Table~\ref{tab:prop} (a claim derived from a non-\textsc{valid} parent is itself
\textsc{stale}), staleness is closed under subsequent derivation, so no
\textsc{valid} claim can be produced from a \textsc{stale} ancestor.
\end{proof}

These results are the substrate's safety core: trustworthiness can only fall,
sensitivity can only rise, validity can only shrink, and staleness only spreads
downward---all as typed preconditions of producing a derived claim, not as
optional metadata a layer may forget.

\section{Calibrated Confidence Under Drift}\label{sec:conf}
For a stationary stream we attach split-conformal confidence: given calibration
nonconformity scores $\{r_i\}_{i=1}^{n}$ and target miscoverage $\alpha$, the
half-width $q$ is the $\lceil(n+1)(1-\alpha)\rceil/n$ empirical quantile, giving
marginal coverage $\Pr(y\in[\hat y\pm q])\ge 1-\alpha$ under
exchangeability~\cite{vovk2005algorithmic}. Exchangeability fails under drift, so
we additionally support ACI~\cite{gibbs2021adaptive}, which updates the
miscoverage online,
\begin{equation}
\alpha_{t+1}=\alpha_t+\gamma\,(\alpha-\mathrm{err}_t),\quad
\mathrm{err}_t=\mathbf{1}[y_t\notin C_t],
\end{equation}
maintaining long-run coverage near $1-\alpha$ without distributional
assumptions. The DAC's confidence field thus carries a guarantee that itself
adapts to non-stationarity, linking the confidence dimension to the drift
dimension within a single object.

\section{Drift-Triggered Invalidation}\label{sec:drift}
A monitor governs each input stream using the Page--Hinkley
test~\cite{page1954continuous} for online mean shift and a two-sample
Kolmogorov--Smirnov test~\cite{massey1951ks} for distributional shift; adaptive
windowing~\cite{bifet2007adwin} is a drop-in alternative. On an alarm, the store
applies Theorem~\ref{thm:cascade}, transitioning the monitored claims and all
their provenance descendants to \textsc{stale} while leaving independent claims
untouched. The system therefore represents, explicitly and queryably, the moment
its own knowledge expires.

\section{Implementation}\label{sec:impl}
The reference implementation is $\sim$450 lines of Python with no proprietary
dependencies: Ed25519 signatures~\cite{bernstein2012ed25519} via the
\texttt{cryptography} library; a SHA-256 hash chain~\cite{schneier1999audit} in
SQLite; conformal and drift mathematics in NumPy/SciPy. Producers are
non-human identities with verifiable keys; the store persists claims with their
chain links and provenance edges and exposes \texttt{cascade\_stale}. A
stdlib-only command line exposes the substrate to workflow orchestrators, and an
exporter renders the claim store as an OSCAL assessment-results
document~\cite{nist_oscal} mapping DAC properties to NIST
controls~\cite{nist80053}, making runtime state consumable by existing
governance tooling.

\section{Evaluation}\label{sec:eval}
We encode the specification as seven falsifiable acceptance properties with
fixed seeds (Table~\ref{tab:eval}). Tampering with a payload invalidates the
signature (T1); altering any stored row breaks the hash chain (T2); a
three-layer chain pulls the decision's confidence down to the weakest link's
$0.92$ (T3) and forces \textsc{regulated}$+$HITL downstream (T4); split-conformal
coverage meets its target (T5); a stream shift cascades \textsc{stale} to exactly
the dependent claims and not to an independent stream (T6); and under a
$3\times$ scale shift introduced midstream, static conformal coverage collapses
to $0.40$ while ACI holds $0.90$ (T7). The last result is the central empirical
point: a static guarantee becomes silently wrong under drift, whereas the
adaptive guarantee, carried inside the DAC, does not.

\begin{table}[t]\centering
\caption{Acceptance properties (reference build).}\label{tab:eval}
\begin{tabular}{@{}cll@{}}
\toprule
\# & Property & Result\\
\midrule
T1 & Signature catches payload tampering & pass\\
T2 & Hash chain catches store tampering & pass\\
T3 & Confidence $=$ weakest link ($\to 0.92$) & pass\\
T4 & \textsc{regulated}$+$HITL propagate & pass\\
T5 & Split-conformal coverage $\ge 1-\alpha$ & pass ($0.885$@$0.90$)\\
T6 & Drift cascades to dependents only & pass ($3/3$)\\
T7 & ACI holds under drift; static fails & pass ($0.90$ vs $0.40$)\\
\bottomrule
\end{tabular}
\end{table}

\section{Limitations}\label{sec:lim}
The substrate closes a cross-cutting gap but introduces honest open problems.
(1) The $\min$ combiner is conservative and under-counts genuinely independent
corroborating evidence; a calibrated fusion rule is future work. (2) Drift in an
\emph{unmonitored} variable is invisible; automatic selection of which
statistics to monitor is unsolved. (3) The DAC attests byte-level provenance, not
semantic meaning---it does not certify that an embedding \emph{means} what its
producer claims. (4) Producer trust is intra-organizational; a federated trust
root and key-revocation layer are required for cross-consortium use. (5)
Conformal coverage here is marginal and long-run, not
conditional~\cite{barber2023beyond}, so rare subpopulations may be
miscalibrated. (6) A \textsc{stale}-but-acted-upon claim has defined provenance
but undefined legal liability. The substrate makes these auditable, not resolved.

\section{Conclusion}
Provenance, calibrated confidence, and drift validity are usually treated as
three separate concerns living in three separate subsystems. We showed they are
one concern and admit one portable primitive---the Drift-Aware Claim---whose
propagation contract has clean lattice semantics and provable closure, and whose
confidence and validity react to non-stationarity by construction. A small
open-source implementation realizes the design and passes a falsifiable
acceptance suite. We view the DAC as infrastructure for the trustworthy
composition and delegation that next-generation autonomous systems will demand.

\bibliographystyle{IEEEtran}
\bibliography{references}

\end{document}
