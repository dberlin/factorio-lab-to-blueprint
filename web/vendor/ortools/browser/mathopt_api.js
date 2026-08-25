var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);
import { loadMathOptRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeEnabled,
  setWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
function shouldUseMathOptBridge() {
  return shouldUseWorkerBridge();
}
class MathOptVarEqVar {
  constructor(firstVariable, secondVariable) {
    __publicField(this, "firstVariable");
    __publicField(this, "secondVariable");
    if (firstVariable.model !== secondVariable.model)
      throw new Error("Variables belong to different MathOpt models.");
    this.firstVariable = firstVariable, this.secondVariable = secondVariable;
  }
  get first_variable() {
    return this.firstVariable;
  }
  get second_variable() {
    return this.secondVariable;
  }
  assertNotBoolean() {
    throw new TypeError("Cannot convert MathOpt variable equality expression to boolean.");
  }
}
var MathOptSolverType = /* @__PURE__ */ ((MathOptSolverType2) => (MathOptSolverType2[MathOptSolverType2.GSCIP = 1] = "GSCIP", MathOptSolverType2[MathOptSolverType2.GUROBI = 2] = "GUROBI", MathOptSolverType2[MathOptSolverType2.GLOP = 3] = "GLOP", MathOptSolverType2[MathOptSolverType2.CP_SAT = 4] = "CP_SAT", MathOptSolverType2[MathOptSolverType2.PDLP = 5] = "PDLP", MathOptSolverType2[MathOptSolverType2.GLPK = 6] = "GLPK", MathOptSolverType2[MathOptSolverType2.OSQP = 7] = "OSQP", MathOptSolverType2[MathOptSolverType2.ECOS = 8] = "ECOS", MathOptSolverType2[MathOptSolverType2.SCS = 9] = "SCS", MathOptSolverType2[MathOptSolverType2.HIGHS = 10] = "HIGHS", MathOptSolverType2[MathOptSolverType2.SANTORINI = 11] = "SANTORINI", MathOptSolverType2[MathOptSolverType2.XPRESS = 13] = "XPRESS", MathOptSolverType2))(MathOptSolverType || {}), MathOptLPAlgorithm = /* @__PURE__ */ ((MathOptLPAlgorithm2) => (MathOptLPAlgorithm2[MathOptLPAlgorithm2.UNSPECIFIED = 0] = "UNSPECIFIED", MathOptLPAlgorithm2[MathOptLPAlgorithm2.PRIMAL_SIMPLEX = 1] = "PRIMAL_SIMPLEX", MathOptLPAlgorithm2[MathOptLPAlgorithm2.DUAL_SIMPLEX = 2] = "DUAL_SIMPLEX", MathOptLPAlgorithm2[MathOptLPAlgorithm2.BARRIER = 3] = "BARRIER", MathOptLPAlgorithm2[MathOptLPAlgorithm2.FIRST_ORDER = 4] = "FIRST_ORDER", MathOptLPAlgorithm2))(MathOptLPAlgorithm || {}), MathOptEmphasis = /* @__PURE__ */ ((MathOptEmphasis2) => (MathOptEmphasis2[MathOptEmphasis2.UNSPECIFIED = 0] = "UNSPECIFIED", MathOptEmphasis2[MathOptEmphasis2.OFF = 1] = "OFF", MathOptEmphasis2[MathOptEmphasis2.LOW = 2] = "LOW", MathOptEmphasis2[MathOptEmphasis2.MEDIUM = 3] = "MEDIUM", MathOptEmphasis2[MathOptEmphasis2.HIGH = 4] = "HIGH", MathOptEmphasis2[MathOptEmphasis2.VERY_HIGH = 5] = "VERY_HIGH", MathOptEmphasis2))(MathOptEmphasis || {}), GScipEmphasis = /* @__PURE__ */ ((GScipEmphasis2) => (GScipEmphasis2[GScipEmphasis2.DEFAULT_EMPHASIS = 0] = "DEFAULT_EMPHASIS", GScipEmphasis2[GScipEmphasis2.COUNTER = 1] = "COUNTER", GScipEmphasis2[GScipEmphasis2.CP_SOLVER = 2] = "CP_SOLVER", GScipEmphasis2[GScipEmphasis2.EASY_CIP = 3] = "EASY_CIP", GScipEmphasis2[GScipEmphasis2.FEASIBILITY = 4] = "FEASIBILITY", GScipEmphasis2[GScipEmphasis2.HARD_LP = 5] = "HARD_LP", GScipEmphasis2[GScipEmphasis2.OPTIMALITY = 6] = "OPTIMALITY", GScipEmphasis2[GScipEmphasis2.PHASE_FEAS = 7] = "PHASE_FEAS", GScipEmphasis2[GScipEmphasis2.PHASE_IMPROVE = 8] = "PHASE_IMPROVE", GScipEmphasis2[GScipEmphasis2.PHASE_PROOF = 9] = "PHASE_PROOF", GScipEmphasis2))(GScipEmphasis || {}), GScipMetaParamValue = /* @__PURE__ */ ((GScipMetaParamValue2) => (GScipMetaParamValue2[GScipMetaParamValue2.DEFAULT_META_PARAM_VALUE = 0] = "DEFAULT_META_PARAM_VALUE", GScipMetaParamValue2[GScipMetaParamValue2.AGGRESSIVE = 1] = "AGGRESSIVE", GScipMetaParamValue2[GScipMetaParamValue2.FAST = 2] = "FAST", GScipMetaParamValue2[GScipMetaParamValue2.OFF = 3] = "OFF", GScipMetaParamValue2))(GScipMetaParamValue || {}), PdlpOptimalityNorm = /* @__PURE__ */ ((PdlpOptimalityNorm2) => (PdlpOptimalityNorm2[PdlpOptimalityNorm2.UNSPECIFIED = 0] = "UNSPECIFIED", PdlpOptimalityNorm2[PdlpOptimalityNorm2.L_INF = 1] = "L_INF", PdlpOptimalityNorm2[PdlpOptimalityNorm2.L2 = 2] = "L2", PdlpOptimalityNorm2[PdlpOptimalityNorm2.L_INF_COMPONENTWISE = 3] = "L_INF_COMPONENTWISE", PdlpOptimalityNorm2))(PdlpOptimalityNorm || {}), PdlpSchedulerType = /* @__PURE__ */ ((PdlpSchedulerType2) => (PdlpSchedulerType2[PdlpSchedulerType2.UNSPECIFIED = 0] = "UNSPECIFIED", PdlpSchedulerType2[PdlpSchedulerType2.GOOGLE_THREADPOOL = 1] = "GOOGLE_THREADPOOL", PdlpSchedulerType2[PdlpSchedulerType2.EIGEN_THREADPOOL = 3] = "EIGEN_THREADPOOL", PdlpSchedulerType2))(PdlpSchedulerType || {}), PdlpRestartStrategy = /* @__PURE__ */ ((PdlpRestartStrategy2) => (PdlpRestartStrategy2[PdlpRestartStrategy2.UNSPECIFIED = 0] = "UNSPECIFIED", PdlpRestartStrategy2[PdlpRestartStrategy2.NO_RESTARTS = 1] = "NO_RESTARTS", PdlpRestartStrategy2[PdlpRestartStrategy2.EVERY_MAJOR_ITERATION = 2] = "EVERY_MAJOR_ITERATION", PdlpRestartStrategy2[PdlpRestartStrategy2.ADAPTIVE_HEURISTIC = 3] = "ADAPTIVE_HEURISTIC", PdlpRestartStrategy2[PdlpRestartStrategy2.ADAPTIVE_DISTANCE_BASED = 4] = "ADAPTIVE_DISTANCE_BASED", PdlpRestartStrategy2))(PdlpRestartStrategy || {}), PdlpLinesearchRule = /* @__PURE__ */ ((PdlpLinesearchRule2) => (PdlpLinesearchRule2[PdlpLinesearchRule2.UNSPECIFIED = 0] = "UNSPECIFIED", PdlpLinesearchRule2[PdlpLinesearchRule2.ADAPTIVE_LINESEARCH_RULE = 1] = "ADAPTIVE_LINESEARCH_RULE", PdlpLinesearchRule2[PdlpLinesearchRule2.MALITSKY_POCK_LINESEARCH_RULE = 2] = "MALITSKY_POCK_LINESEARCH_RULE", PdlpLinesearchRule2[PdlpLinesearchRule2.CONSTANT_STEP_SIZE_RULE = 3] = "CONSTANT_STEP_SIZE_RULE", PdlpLinesearchRule2))(PdlpLinesearchRule || {});
class GScipParameters {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    const options = this.options;
    return message([
      enumField(1, options.emphasis, GScipEmphasis),
      enumField(2, options.heuristics, GScipMetaParamValue),
      enumField(3, options.presolve, GScipMetaParamValue),
      enumField(4, options.separating, GScipMetaParamValue),
      ...mapFields(5, options.boolParams ?? options.bool_params, fieldBool),
      ...mapFields(6, options.intParams ?? options.int_params, fieldVarint),
      ...mapFields(7, options.longParams ?? options.long_params, fieldVarint),
      ...mapFields(8, options.realParams ?? options.real_params, fieldDouble),
      ...mapFields(9, options.charParams ?? options.char_params, fieldString),
      ...mapFields(10, options.stringParams ?? options.string_params, fieldString),
      optionalBoolField(11, options.silenceOutput ?? options.silence_output),
      optionalBoolField(12, options.printDetailedSolvingStats ?? options.print_detailed_solving_stats),
      optionalBoolField(13, options.printScipModel ?? options.print_scip_model),
      optionalStringField(14, options.searchLogsFilename ?? options.search_logs_filename),
      optionalStringField(15, options.detailedSolvingStatsFilename ?? options.detailed_solving_stats_filename),
      optionalStringField(16, options.scipModelFilename ?? options.scip_model_filename),
      optionalVarintField(17, options.numSolutions ?? options.num_solutions),
      optionalDoubleField(18, options.objectiveLimit ?? options.objective_limit)
    ]);
  }
}
class GlopParameters {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    const options = this.options;
    return message([
      optionalBoolField(16, options.useScaling ?? options.use_scaling),
      optionalDoubleField(26, options.maxTimeInSeconds ?? options.max_time_in_seconds),
      optionalBoolField(31, options.useDualSimplex ?? options.use_dual_simplex),
      optionalBoolField(34, options.usePreprocessing ?? options.use_preprocessing)
    ]);
  }
}
class PdlpParameters {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    const options = this.options;
    return message([
      fieldMessageIfPresent(1, encodePdlpTerminationCriteria(options.terminationCriteria ?? options.termination_criteria)),
      optionalVarintField(2, options.numThreads ?? options.num_threads),
      optionalBoolField(3, options.recordIterationStats ?? options.record_iteration_stats),
      optionalVarintField(4, options.majorIterationFrequency ?? options.major_iteration_frequency),
      optionalVarintField(5, options.terminationCheckFrequency ?? options.termination_check_frequency),
      enumField(6, options.restartStrategy ?? options.restart_strategy, PdlpRestartStrategy),
      optionalDoubleField(7, options.primalWeightUpdateSmoothing ?? options.primal_weight_update_smoothing),
      optionalDoubleField(8, options.initialPrimalWeight ?? options.initial_primal_weight),
      optionalVarintField(9, options.lInfRuizIterations ?? options.l_inf_ruiz_iterations),
      optionalBoolField(10, options.l2NormRescaling ?? options.l2_norm_rescaling),
      optionalDoubleField(11, options.sufficientReductionForRestart ?? options.sufficient_reduction_for_restart),
      enumField(12, options.linesearchRule ?? options.linesearch_rule, PdlpLinesearchRule),
      optionalDoubleField(17, options.necessaryReductionForRestart ?? options.necessary_reduction_for_restart),
      optionalDoubleField(25, options.initialStepSizeScaling ?? options.initial_step_size_scaling),
      optionalVarintField(26, options.verbosityLevel ?? options.verbosity_level),
      optionalVarintField(27, options.numShards ?? options.num_shards),
      fieldPackedVarintsIfPresent(28, options.randomProjectionSeeds ?? options.random_projection_seeds),
      optionalDoubleField(22, options.infiniteConstraintBoundThreshold ?? options.infinite_constraint_bound_threshold),
      optionalBoolField(23, options.useDiagonalQpTrustRegionSolver ?? options.use_diagonal_qp_trust_region_solver),
      optionalDoubleField(24, options.diagonalQpTrustRegionSolverTolerance ?? options.diagonal_qp_trust_region_solver_tolerance),
      optionalDoubleField(31, options.logIntervalSeconds ?? options.log_interval_seconds),
      enumField(32, options.schedulerType ?? options.scheduler_type, PdlpSchedulerType),
      optionalBoolField(30, options.useFeasibilityPolishing ?? options.use_feasibility_polishing),
      optionalBoolField(33, options.applyFeasibilityPolishingAfterLimitsReached ?? options.apply_feasibility_polishing_after_limits_reached),
      optionalBoolField(34, options.applyFeasibilityPolishingIfSolverIsInterrupted ?? options.apply_feasibility_polishing_if_solver_is_interrupted)
    ]);
  }
}
class GlpkParameters {
  constructor(options = {}) {
    __publicField(this, "computeUnboundRaysIfPossible");
    __publicField(this, "compute_unbound_rays_if_possible");
    this.computeUnboundRaysIfPossible = options.computeUnboundRaysIfPossible ?? options.compute_unbound_rays_if_possible, this.compute_unbound_rays_if_possible = this.computeUnboundRaysIfPossible;
  }
  toProtoBytes() {
    return message([
      this.computeUnboundRaysIfPossible === void 0 ? empty() : fieldBool(1, this.computeUnboundRaysIfPossible)
    ]);
  }
}
class MathOptSolveInterrupter {
  constructor() {
    __publicField(this, "interruptedValue", !1);
  }
  interrupt() {
    this.interruptedValue = !0;
  }
  get interrupted() {
    return this.interruptedValue;
  }
  isInterrupted() {
    return this.interruptedValue;
  }
  is_interrupted() {
    return this.isInterrupted();
  }
}
class MathOptSolveParameters {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    return encodeMathOptSolveParameters(this.options) ?? empty();
  }
}
class MathOptSparseVectorFilter {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    return encodeSparseVectorFilter(this.options);
  }
}
class MathOptSolutionHint {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    const variableValues = this.options.variableValues ?? this.options.variable_values, dualValues = this.options.dualValues ?? this.options.dual_values;
    return message([
      fieldMessageIfPresent(1, variableValues === void 0 ? null : encodeSparseDoubleVector(variableValues)),
      fieldMessageIfPresent(2, dualValues === void 0 ? null : encodeLinearConstraintDoubleVector(dualValues.map((entry) => {
        const normalized = entry, linearConstraint = normalized.linearConstraint ?? normalized.linear_constraint;
        if (!linearConstraint) throw new Error("MathOpt solution hint dual values must include a linear constraint.");
        return { linearConstraint, value: entry.value };
      })))
    ]);
  }
}
class MathOptModelSolveParameters {
  constructor(options = {}) {
    __publicField(this, "options", options);
  }
  toProtoBytes() {
    const options = this.options, solutionHints = options.solutionHints ?? options.solution_hints, branchingPriorities = options.branchingPriorities ?? options.branching_priorities, lazyLinearConstraintIds = options.lazyLinearConstraintIds ?? options.lazy_linear_constraint_ids ?? (options.lazyLinearConstraints ?? options.lazy_linear_constraints)?.map(
      (constraint) => typeof constraint == "object" ? constraint.id : constraint
    );
    return message([
      fieldMessageIfPresent(1, modelFilterBytes(options.variableValuesFilter ?? options.variable_values_filter)),
      fieldMessageIfPresent(2, modelFilterBytes(options.dualValuesFilter ?? options.dual_values_filter)),
      fieldMessageIfPresent(10, modelFilterBytes(options.quadraticDualValuesFilter ?? options.quadratic_dual_values_filter)),
      fieldMessageIfPresent(3, modelFilterBytes(options.reducedCostsFilter ?? options.reduced_costs_filter)),
      fieldMessageIfPresent(4, options.initialBasis ?? options.initial_basis),
      ...(solutionHints ?? []).map((hint) => fieldMessage(5, solutionHintBytes(hint))),
      fieldMessageIfPresent(6, branchingPriorities === void 0 ? null : encodeVariableInt32Vector(branchingPriorities)),
      fieldPackedVarintsIfPresent(9, lazyLinearConstraintIds)
    ]);
  }
  static onlySomePrimalVariables(variables) {
    return new MathOptModelSolveParameters({
      variableValuesFilter: { elements: variables, filterByIds: !0 }
    });
  }
  static only_some_primal_variables(variables) {
    return MathOptModelSolveParameters.onlySomePrimalVariables(variables);
  }
}
class MathOptQuadraticTermKey {
  constructor(firstVariable, secondVariable) {
    __publicField(this, "firstVariable");
    __publicField(this, "secondVariable");
    if (firstVariable.model !== secondVariable.model)
      throw new Error("Quadratic term variables belong to different MathOpt models.");
    firstVariable.id <= secondVariable.id ? (this.firstVariable = firstVariable, this.secondVariable = secondVariable) : (this.firstVariable = secondVariable, this.secondVariable = firstVariable);
  }
  equals(other) {
    return this.firstVariable.equals(other.firstVariable) && this.secondVariable.equals(other.secondVariable);
  }
  toString() {
    return `${this.firstVariable.toString()} * ${this.secondVariable.toString()}`;
  }
}
class MathOptLinearExpression {
  constructor(terms = [], offset = 0) {
    __publicField(this, "offset");
    __publicField(this, "terms");
    if (typeof terms == "number") {
      this.terms = readonlyMap(/* @__PURE__ */ new Map()), this.offset = terms;
      return;
    }
    if (terms instanceof MathOptLinearExpression || terms instanceof MathOptVariable || isLinearTerm(terms)) {
      const expression = asFlatLinearExpression(terms);
      this.terms = expression.terms, this.offset = expression.offset + offset;
      return;
    }
    const merged = /* @__PURE__ */ new Map();
    for (const term of terms) {
      if (!isLinearTerm(term))
        throw new TypeError("unsupported type in iterable argument");
      const existing = findVariableKey(merged, term.variable), next = (existing ? merged.get(existing) ?? 0 : 0) + term.coefficient;
      existing && merged.delete(existing), next !== 0 && merged.set(term.variable, next);
    }
    this.terms = readonlyMap(merged), this.offset = offset;
  }
  add(input) {
    const rhs = asFlatLinearExpression(input);
    return new MathOptLinearExpression([
      ...linearTermEntries(this),
      ...linearTermEntries(rhs)
    ], this.offset + rhs.offset);
  }
  subtract(input) {
    return this.add(asFlatLinearExpression(input).multiply(-1));
  }
  multiply(coefficient) {
    return new MathOptLinearExpression(
      linearTermEntries(this).map((term) => ({
        variable: term.variable,
        coefficient: term.coefficient * coefficient
      })),
      this.offset * coefficient
    );
  }
  toString() {
    return formatExpression(this.offset, linearTermEntries(this), []);
  }
  evaluate(variableValues) {
    return evaluateExpression(this, variableValues);
  }
}
class MathOptQuadraticExpression {
  constructor(linearTerms = [], quadraticTerms = [], offset = 0) {
    __publicField(this, "offset");
    __publicField(this, "linearTerms");
    __publicField(this, "quadraticTerms");
    if (typeof linearTerms == "number" || linearTerms instanceof MathOptVariable || linearTerms instanceof MathOptLinearExpression || linearTerms instanceof MathOptQuadraticExpression || isLinearTerm(linearTerms) || isQuadraticTerm(linearTerms)) {
      const expression = asFlatQuadraticExpression(linearTerms);
      this.linearTerms = expression.linearTerms, this.quadraticTerms = expression.quadraticTerms, this.offset = expression.offset + offset;
      return;
    }
    this.linearTerms = new MathOptLinearExpression(linearTerms).terms;
    const merged = /* @__PURE__ */ new Map();
    for (const term of quadraticTerms) {
      if (!isQuadraticTerm(term))
        throw new TypeError("unsupported type in iterable argument");
      const key = new MathOptQuadraticTermKey(term.firstVariable, term.secondVariable), existing = findQuadraticKey(merged, key), next = (existing ? merged.get(existing) ?? 0 : 0) + term.coefficient;
      existing && merged.delete(existing), next !== 0 && merged.set(key, next);
    }
    this.quadraticTerms = readonlyMap(merged), this.offset = offset;
  }
  add(input) {
    const rhs = asFlatQuadraticExpression(input);
    return new MathOptQuadraticExpression(
      [...linearTermEntriesFromMap(this.linearTerms), ...linearTermEntriesFromMap(rhs.linearTerms)],
      [...quadraticTermEntries(this), ...quadraticTermEntries(rhs)],
      this.offset + rhs.offset
    );
  }
  subtract(input) {
    return this.add(asFlatQuadraticExpression(input).multiply(-1));
  }
  multiply(coefficient) {
    return new MathOptQuadraticExpression(
      linearTermEntriesFromMap(this.linearTerms).map((term) => ({
        variable: term.variable,
        coefficient: term.coefficient * coefficient
      })),
      quadraticTermEntries(this).map((term) => ({
        firstVariable: term.firstVariable,
        secondVariable: term.secondVariable,
        coefficient: term.coefficient * coefficient
      })),
      this.offset * coefficient
    );
  }
  evaluate(variableValues) {
    return evaluateExpression(this, variableValues);
  }
  toString() {
    return formatExpression(this.offset, linearTermEntriesFromMap(this.linearTerms), quadraticTermEntries(this));
  }
}
class MathOptBoundedExpression {
  constructor(lowerBound, expression, upperBound) {
    __publicField(this, "lowerBound", lowerBound);
    __publicField(this, "expression", expression);
    __publicField(this, "upperBound", upperBound);
  }
  get lower_bound() {
    return this.lowerBound;
  }
  get upper_bound() {
    return this.upperBound;
  }
  assertNotBoolean() {
    throw new TypeError("__bool__ is unsupported for two-sided or ranged linear inequality.");
  }
  toString() {
    return `${formatBound(this.lowerBound)} <= ${String(this.expression)} <= ${formatBound(this.upperBound)}`;
  }
}
class MathOptLowerBoundedExpression {
  constructor(lowerBound, expression) {
    __publicField(this, "lowerBound", lowerBound);
    __publicField(this, "expression", expression);
    __publicField(this, "upperBound", Number.POSITIVE_INFINITY);
  }
  get lower_bound() {
    return this.lowerBound;
  }
  get upper_bound() {
    return this.upperBound;
  }
  toBoundedExpression(upperBound) {
    return new MathOptBoundedExpression(this.lowerBound, this.expression, upperBound);
  }
  assertNotBoolean() {
    throw new TypeError("__bool__ is unsupported for two-sided or ranged linear inequality.");
  }
  toString() {
    return `${String(this.expression)} >= ${formatBound(this.lowerBound)}`;
  }
}
class MathOptUpperBoundedExpression {
  constructor(expression, upperBound) {
    __publicField(this, "expression", expression);
    __publicField(this, "upperBound", upperBound);
    __publicField(this, "lowerBound", Number.NEGATIVE_INFINITY);
  }
  get lower_bound() {
    return this.lowerBound;
  }
  get upper_bound() {
    return this.upperBound;
  }
  toBoundedExpression(lowerBound) {
    return new MathOptBoundedExpression(lowerBound, this.expression, this.upperBound);
  }
  assertNotBoolean() {
    throw new TypeError("__bool__ is unsupported for two-sided or ranged linear inequality.");
  }
  toString() {
    return `${String(this.expression)} <= ${formatBound(this.upperBound)}`;
  }
}
const terminationReasonNames = {
  0: "TERMINATION_REASON_UNSPECIFIED",
  1: "TERMINATION_REASON_OPTIMAL",
  2: "TERMINATION_REASON_INFEASIBLE",
  3: "TERMINATION_REASON_UNBOUNDED",
  4: "TERMINATION_REASON_INFEASIBLE_OR_UNBOUNDED",
  5: "TERMINATION_REASON_IMPRECISE",
  6: "TERMINATION_REASON_NO_SOLUTION_FOUND",
  7: "TERMINATION_REASON_NUMERICAL_ERROR",
  8: "TERMINATION_REASON_OTHER_ERROR",
  9: "TERMINATION_REASON_FEASIBLE"
}, terminationLimitNames = {
  0: "LIMIT_UNSPECIFIED",
  1: "LIMIT_UNDETERMINED",
  2: "LIMIT_ITERATION",
  3: "LIMIT_TIME",
  4: "LIMIT_NODE",
  5: "LIMIT_SOLUTION",
  6: "LIMIT_MEMORY",
  7: "LIMIT_OBJECTIVE",
  8: "LIMIT_NORM",
  9: "LIMIT_INTERRUPTED",
  10: "LIMIT_SLOW_PROGRESS",
  11: "LIMIT_OTHER",
  12: "LIMIT_CUTOFF"
}, solutionStatusNames = {
  0: "SOLUTION_STATUS_UNSPECIFIED",
  1: "SOLUTION_STATUS_UNDETERMINED",
  2: "SOLUTION_STATUS_FEASIBLE",
  3: "SOLUTION_STATUS_INFEASIBLE"
}, feasibilityStatusNames = {
  0: "FEASIBILITY_STATUS_UNSPECIFIED",
  1: "FEASIBILITY_STATUS_UNDETERMINED",
  2: "FEASIBILITY_STATUS_FEASIBLE",
  3: "FEASIBILITY_STATUS_INFEASIBLE"
}, basisStatusNames = {
  0: "BASIS_STATUS_UNSPECIFIED",
  1: "BASIS_STATUS_FREE",
  2: "BASIS_STATUS_AT_LOWER_BOUND",
  3: "BASIS_STATUS_AT_UPPER_BOUND",
  4: "BASIS_STATUS_FIXED_VALUE",
  5: "BASIS_STATUS_BASIC"
};
let mathOptModulePromise = null;
function loadMathOptModule() {
  return mathOptModulePromise ?? (mathOptModulePromise = loadMathOptRuntime()), mathOptModulePromise;
}
class MathOptModel {
  constructor(name = "") {
    __publicField(this, "name");
    __publicField(this, "variableData", []);
    __publicField(this, "constraints", []);
    __publicField(this, "indicatorConstraints", []);
    __publicField(this, "objectiveDataValue", {
      maximize: !1,
      linearTerms: [],
      quadraticTerms: [],
      offset: 0
    });
    __publicField(this, "objective");
    this.name = name, this.objective = new MathOptObjective(this);
  }
  addVariable(options = {}) {
    const variable = {
      id: this.variableData.length,
      lowerBound: options.lowerBound ?? options.lb ?? Number.NEGATIVE_INFINITY,
      upperBound: options.upperBound ?? options.ub ?? Number.POSITIVE_INFINITY,
      integer: options.integer ?? options.isInteger ?? options.is_integer ?? !1,
      name: options.name ?? "",
      deleted: !1
    };
    return this.variableData.push(variable), new MathOptVariable(this, variable);
  }
  add_variable(options = {}) {
    return this.addVariable(options);
  }
  addIntegerVariable(options = {}) {
    return this.addVariable({ ...options, integer: !0 });
  }
  add_integer_variable(options = {}) {
    return this.addIntegerVariable(options);
  }
  addBinaryVariable(options = {}) {
    return this.addVariable({ ...options, lowerBound: 0, upperBound: 1, integer: !0 });
  }
  add_binary_variable(options = {}) {
    return this.addBinaryVariable(options);
  }
  addLinearConstraint(options = {}) {
    const id = this.constraints.length, normalizedOptions = this.normalizeLinearConstraintOptions(options), expression = normalizedOptions.expression === void 0 ? new MathOptLinearExpression(normalizedOptions.terms ?? []) : asFlatLinearExpression(normalizedOptions.expression).add(new MathOptLinearExpression(normalizedOptions.terms ?? []));
    if (!Number.isFinite(expression.offset))
      throw new Error("linear constraint expression has an infinite offset.");
    const constraint = {
      id,
      lowerBound: (normalizedOptions.lowerBound ?? Number.NEGATIVE_INFINITY) - expression.offset,
      upperBound: (normalizedOptions.upperBound ?? Number.POSITIVE_INFINITY) - expression.offset,
      terms: linearTermEntries(expression),
      name: normalizedOptions.name ?? "",
      deleted: !1
    };
    return this.constraints.push(constraint), new MathOptLinearConstraint(this, constraint);
  }
  add_linear_constraint(options = {}) {
    return this.addLinearConstraint(options);
  }
  addIndicatorConstraint(options = {}) {
    const id = this.indicatorConstraints.length, normalizedOptions = this.normalizeIndicatorConstraintOptions(options);
    normalizedOptions.indicator && this.assertOwnsVariable(normalizedOptions.indicator);
    const expression = normalizedOptions.expression === void 0 ? new MathOptLinearExpression(normalizedOptions.terms ?? []) : asFlatLinearExpression(normalizedOptions.expression).add(new MathOptLinearExpression(normalizedOptions.terms ?? []));
    if (!Number.isFinite(expression.offset))
      throw new Error("indicator constraint expression has an infinite offset.");
    const constraint = {
      id,
      indicator: normalizedOptions.indicator,
      activateOnZero: normalizedOptions.activateOnZero ?? !1,
      lowerBound: (normalizedOptions.lowerBound ?? Number.NEGATIVE_INFINITY) - expression.offset,
      upperBound: (normalizedOptions.upperBound ?? Number.POSITIVE_INFINITY) - expression.offset,
      terms: linearTermEntries(expression),
      name: normalizedOptions.name ?? "",
      deleted: !1
    };
    return this.indicatorConstraints.push(constraint), new MathOptIndicatorConstraint(this, constraint);
  }
  add_indicator_constraint(options = {}) {
    return this.addIndicatorConstraint(options);
  }
  normalizeLinearConstraintOptions(options) {
    if (options instanceof MathOptBoundedExpression)
      return { lowerBound: options.lowerBound, upperBound: options.upperBound, expression: options.expression };
    if (options instanceof MathOptLowerBoundedExpression)
      return { lowerBound: options.lowerBound, upperBound: Number.POSITIVE_INFINITY, expression: options.expression };
    if (options instanceof MathOptUpperBoundedExpression)
      return { lowerBound: Number.NEGATIVE_INFINITY, upperBound: options.upperBound, expression: options.expression };
    if (options === null || typeof options != "object" || Array.isArray(options))
      throw new TypeError(`Unsupported type for bounded_expr argument: ${mathOptOperandType(options)}`);
    return {
      ...options,
      lowerBound: options.lowerBound ?? options.lb,
      upperBound: options.upperBound ?? options.ub,
      expression: options.expression ?? options.expr
    };
  }
  normalizeIndicatorConstraintOptions(options) {
    if (options === null || typeof options != "object" || Array.isArray(options))
      throw new TypeError(`Unsupported type for indicator constraint options: ${mathOptOperandType(options)}`);
    const implied = options.impliedConstraint ?? options.implied_constraint;
    return implied instanceof MathOptBoundedExpression ? {
      indicator: options.indicator,
      activateOnZero: options.activateOnZero ?? options.activate_on_zero,
      lowerBound: implied.lowerBound,
      upperBound: implied.upperBound,
      expression: implied.expression,
      name: options.name
    } : implied instanceof MathOptLowerBoundedExpression ? {
      indicator: options.indicator,
      activateOnZero: options.activateOnZero ?? options.activate_on_zero,
      lowerBound: implied.lowerBound,
      upperBound: Number.POSITIVE_INFINITY,
      expression: implied.expression,
      name: options.name
    } : implied instanceof MathOptUpperBoundedExpression ? {
      indicator: options.indicator,
      activateOnZero: options.activateOnZero ?? options.activate_on_zero,
      lowerBound: Number.NEGATIVE_INFINITY,
      upperBound: implied.upperBound,
      expression: implied.expression,
      name: options.name
    } : {
      indicator: options.indicator,
      activateOnZero: options.activateOnZero ?? options.activate_on_zero,
      lowerBound: options.lowerBound ?? options.lower_bound ?? options.lb,
      upperBound: options.upperBound ?? options.upper_bound ?? options.ub,
      expression: options.expression ?? options.expr,
      terms: options.terms,
      name: options.name
    };
  }
  deleteVariable(variable) {
    if (this.assertOwnsVariable(variable), variable.data.deleted)
      throw new Error(`Variable ${variable.id} has already been deleted.`);
    variable.data.deleted = !0;
    for (const constraint of this.constraints)
      constraint.terms = constraint.terms.filter((term) => term.variable.id !== variable.id);
    for (const constraint of this.indicatorConstraints)
      constraint.terms = constraint.terms.filter((term) => term.variable.id !== variable.id), constraint.indicator?.id === variable.id && (constraint.indicator = void 0);
    this.objectiveDataValue.linearTerms = this.objectiveDataValue.linearTerms.filter((term) => term.variable.id !== variable.id), this.objectiveDataValue.quadraticTerms = this.objectiveDataValue.quadraticTerms.filter((term) => term.firstVariable.id !== variable.id && term.secondVariable.id !== variable.id);
  }
  delete_variable(variable) {
    this.deleteVariable(variable);
  }
  deleteLinearConstraint(constraint) {
    if (this.assertOwnsConstraint(constraint), constraint.data.deleted)
      throw new Error(`Linear constraint ${constraint.id} has already been deleted.`);
    constraint.data.deleted = !0;
  }
  delete_linear_constraint(constraint) {
    this.deleteLinearConstraint(constraint);
  }
  variablesList() {
    return this.variableData.filter((variable) => !variable.deleted).map((variable) => new MathOptVariable(this, variable));
  }
  variables() {
    return this.variablesList();
  }
  getNumVariables() {
    return this.variablesList().length;
  }
  get_num_variables() {
    return this.getNumVariables();
  }
  getNextVariableId() {
    return this.variableData.length;
  }
  get_next_variable_id() {
    return this.getNextVariableId();
  }
  ensureNextVariableIdAtLeast(id) {
    for (; this.variableData.length < id; ) {
      const placeholderId = this.variableData.length;
      this.variableData.push({
        id: placeholderId,
        lowerBound: Number.NEGATIVE_INFINITY,
        upperBound: Number.POSITIVE_INFINITY,
        integer: !1,
        name: "",
        deleted: !0
      });
    }
  }
  ensure_next_variable_id_at_least(id) {
    this.ensureNextVariableIdAtLeast(id);
  }
  hasVariable(id) {
    return !!this.getVariable(id);
  }
  has_variable(id) {
    return this.hasVariable(id);
  }
  getVariable(id, validate = !0) {
    const variable = this.variableData[id];
    if (variable && !variable.deleted) return new MathOptVariable(this, variable);
    if (!validate)
      return new MathOptVariable(this, variable ?? {
        id,
        lowerBound: Number.NEGATIVE_INFINITY,
        upperBound: Number.POSITIVE_INFINITY,
        integer: !1,
        name: "",
        deleted: !0
      });
  }
  get_variable(id, options) {
    const variable = this.getVariable(id, options?.validate ?? !0);
    if (!variable) throw new Error(`Variable ${id} does not exist.`);
    return variable;
  }
  linearConstraints() {
    return this.constraints.filter((constraint) => !constraint.deleted).map((constraint) => new MathOptLinearConstraint(this, constraint));
  }
  linear_constraints() {
    return this.linearConstraints();
  }
  getNumLinearConstraints() {
    return this.linearConstraints().length;
  }
  get_num_linear_constraints() {
    return this.getNumLinearConstraints();
  }
  getNextLinearConstraintId() {
    return this.constraints.length;
  }
  get_next_linear_constraint_id() {
    return this.getNextLinearConstraintId();
  }
  ensureNextLinearConstraintIdAtLeast(id) {
    for (; this.constraints.length < id; ) {
      const placeholderId = this.constraints.length;
      this.constraints.push({
        id: placeholderId,
        lowerBound: Number.NEGATIVE_INFINITY,
        upperBound: Number.POSITIVE_INFINITY,
        terms: [],
        name: "",
        deleted: !0
      });
    }
  }
  ensure_next_linear_constraint_id_at_least(id) {
    this.ensureNextLinearConstraintIdAtLeast(id);
  }
  hasLinearConstraint(id) {
    return !!this.getLinearConstraint(id);
  }
  has_linear_constraint(id) {
    return this.hasLinearConstraint(id);
  }
  getLinearConstraint(id, validate = !0) {
    const constraint = this.constraints[id];
    if (constraint && !constraint.deleted) return new MathOptLinearConstraint(this, constraint);
    if (!validate)
      return new MathOptLinearConstraint(this, constraint ?? {
        id,
        lowerBound: Number.NEGATIVE_INFINITY,
        upperBound: Number.POSITIVE_INFINITY,
        terms: [],
        name: "",
        deleted: !0
      });
  }
  get_linear_constraint(id, options) {
    const constraint = this.getLinearConstraint(id, options?.validate ?? !0);
    if (!constraint) throw new Error(`Linear constraint ${id} does not exist.`);
    return constraint;
  }
  maximize(terms, offset = 0) {
    this.objectiveDataValue = objectiveData(!0, terms, offset);
  }
  minimize(terms, offset = 0) {
    this.objectiveDataValue = objectiveData(!1, terms, offset);
  }
  maximizeLinearObjective(terms, offset = 0) {
    this.setLinearObjective(terms, !0, offset);
  }
  maximize_linear_objective(terms, offset = 0) {
    this.maximizeLinearObjective(terms, offset);
  }
  minimizeLinearObjective(terms, offset = 0) {
    this.setLinearObjective(terms, !1, offset);
  }
  minimize_linear_objective(terms, offset = 0) {
    this.minimizeLinearObjective(terms, offset);
  }
  setObjective(terms, isMaximize, offset = 0) {
    this.objectiveDataValue = objectiveData(isMaximize, terms, offset);
  }
  set_objective(terms, is_maximize, offset = 0) {
    this.setObjective(terms, is_maximize, offset);
  }
  setLinearObjective(terms, isMaximize, offset = 0) {
    this.objectiveDataValue = linearObjectiveData(isMaximize, terms, offset);
  }
  set_linear_objective(terms, is_maximize, offset = 0) {
    this.setLinearObjective(terms, is_maximize, offset);
  }
  setQuadraticObjective(terms, isMaximize, offset = 0) {
    this.setObjective(terms, isMaximize, offset);
  }
  set_quadratic_objective(terms, is_maximize, offset = 0) {
    this.setQuadraticObjective(terms, is_maximize, offset);
  }
  columnNonzeros(variable) {
    return this.assertOwnsVariable(variable), variable.assertLive(), this.constraints.filter((constraint) => !constraint.deleted && constraint.terms.some((term) => term.variable.id === variable.id && term.coefficient !== 0)).map((constraint) => new MathOptLinearConstraint(this, constraint));
  }
  column_nonzeros(variable) {
    return this.columnNonzeros(variable);
  }
  rowNonzeros(constraint) {
    return this.assertOwnsConstraint(constraint), constraint.assertLive(), constraint.terms().map((term) => term.variable);
  }
  row_nonzeros(constraint) {
    return this.rowNonzeros(constraint);
  }
  linearConstraintMatrixEntries() {
    return this.constraints.filter((constraint) => !constraint.deleted).flatMap((constraint) => {
      const linearConstraint = new MathOptLinearConstraint(this, constraint);
      return constraint.terms.filter((term) => term.coefficient !== 0).map((term) => ({
        linearConstraint,
        linear_constraint: linearConstraint,
        variable: term.variable,
        coefficient: term.coefficient
      }));
    });
  }
  linear_constraint_matrix_entries() {
    return this.linearConstraintMatrixEntries();
  }
  get objectiveData() {
    return this.objectiveDataValue;
  }
  set objectiveData(value) {
    this.objectiveDataValue = value;
  }
  variableName(id) {
    return this.variableData[id]?.name ?? String(id);
  }
  linearConstraintName(id) {
    return this.constraints[id]?.name ?? String(id);
  }
  snapshot() {
    return {
      variables: this.variableData.map((variable) => ({ ...variable })),
      linearConstraints: this.constraints.map((constraint) => ({
        id: constraint.id,
        lowerBound: constraint.lowerBound,
        upperBound: constraint.upperBound,
        terms: constraint.terms.map((term) => ({
          variableId: term.variable.id,
          coefficient: term.coefficient
        })),
        name: constraint.name,
        deleted: constraint.deleted
      })),
      indicatorConstraints: this.indicatorConstraints.map((constraint) => ({
        id: constraint.id,
        indicatorId: constraint.indicator?.id,
        activateOnZero: constraint.activateOnZero,
        lowerBound: constraint.lowerBound,
        upperBound: constraint.upperBound,
        terms: constraint.terms.map((term) => ({
          variableId: term.variable.id,
          coefficient: term.coefficient
        })),
        name: constraint.name,
        deleted: constraint.deleted
      })),
      objective: {
        maximize: this.objectiveDataValue.maximize,
        offset: this.objectiveDataValue.offset,
        linearTerms: this.objectiveDataValue.linearTerms.map((term) => ({
          variableId: term.variable.id,
          coefficient: term.coefficient
        })),
        quadraticTerms: this.objectiveDataValue.quadraticTerms.map((term) => ({
          firstVariableId: Math.min(term.firstVariable.id, term.secondVariable.id),
          secondVariableId: Math.max(term.firstVariable.id, term.secondVariable.id),
          coefficient: term.coefficient
        }))
      }
    };
  }
  encodeModelUpdateSince(snapshot, options = {}) {
    return encodeModelUpdate(this, snapshot, options);
  }
  assertOwnsVariable(variable) {
    if (variable.model !== this)
      throw new Error("Variable belongs to a different MathOpt model.");
    variable.assertLive();
  }
  assertOwnsConstraint(constraint) {
    if (constraint.model !== this)
      throw new Error("Linear constraint belongs to a different MathOpt model.");
    constraint.assertLive();
  }
  encodeModelProto(options = {}) {
    const removeNames = options.removeNames ?? !1;
    return message([
      removeNames ? empty() : fieldString(1, this.name),
      fieldMessage(2, this.encodeVariables({ removeNames })),
      fieldMessage(3, this.encodeObjective()),
      fieldMessage(4, this.encodeLinearConstraints({ removeNames })),
      fieldMessage(5, this.encodeLinearConstraintMatrix()),
      ...this.encodeIndicatorConstraints({ removeNames })
    ]);
  }
  encodeVariables(options = {}) {
    const activeVariables = this.variableData.filter((variable) => !variable.deleted);
    return message([
      fieldPackedVarints(1, activeVariables.map((variable) => variable.id)),
      fieldPackedDoubles(2, activeVariables.map((variable) => variable.lowerBound)),
      fieldPackedDoubles(3, activeVariables.map((variable) => variable.upperBound)),
      fieldPackedBools(4, activeVariables.map((variable) => variable.integer)),
      ...options.removeNames ? [] : activeVariables.map((variable) => fieldString(5, variable.name))
    ]);
  }
  encodeObjective() {
    return message([
      fieldBool(1, this.objectiveDataValue.maximize),
      fieldDouble(2, this.objectiveDataValue.offset),
      fieldMessage(3, encodeSparseDoubleVector(this.objectiveDataValue.linearTerms)),
      fieldMessage(4, encodeSparseDoubleMatrix(this.objectiveDataValue.quadraticTerms.map((term) => {
        const rowId = Math.min(term.firstVariable.id, term.secondVariable.id), columnId = Math.max(term.firstVariable.id, term.secondVariable.id);
        return { rowId, columnId, coefficient: term.coefficient };
      })))
    ]);
  }
  encodeLinearConstraints(options = {}) {
    const activeConstraints = this.constraints.filter((constraint) => !constraint.deleted);
    return message([
      fieldPackedVarints(1, activeConstraints.map((constraint) => constraint.id)),
      fieldPackedDoubles(2, activeConstraints.map((constraint) => constraint.lowerBound)),
      fieldPackedDoubles(3, activeConstraints.map((constraint) => constraint.upperBound)),
      ...options.removeNames ? [] : activeConstraints.map((constraint) => fieldString(4, constraint.name))
    ]);
  }
  encodeLinearConstraintMatrix() {
    const entries = this.constraints.filter((constraint) => !constraint.deleted).flatMap((constraint) => [...constraint.terms].filter((term) => term.coefficient !== 0).sort((a, b) => a.variable.id - b.variable.id).map((term) => ({
      rowId: constraint.id,
      columnId: term.variable.id,
      coefficient: term.coefficient
    })));
    return message([
      fieldPackedVarints(1, entries.map((entry) => entry.rowId)),
      fieldPackedVarints(2, entries.map((entry) => entry.columnId)),
      fieldPackedDoubles(3, entries.map((entry) => entry.coefficient))
    ]);
  }
  encodeIndicatorConstraints(options = {}) {
    return this.indicatorConstraints.filter((constraint) => !constraint.deleted).map((constraint) => fieldMessage(9, message([
      fieldVarint(1, constraint.id),
      fieldMessage(2, message([
        constraint.indicator === void 0 ? empty() : fieldVarint(1, constraint.indicator.id),
        constraint.activateOnZero ? fieldBool(6, !0) : empty(),
        fieldMessage(2, encodeSparseDoubleVector(constraint.terms)),
        fieldDouble(3, constraint.lowerBound),
        fieldDouble(4, constraint.upperBound),
        options.removeNames ? empty() : fieldString(5, constraint.name)
      ]))
    ])));
  }
}
class MathOptVariable {
  constructor(model, data) {
    __publicField(this, "model", model);
    __publicField(this, "data", data);
  }
  get id() {
    return this.data.id;
  }
  get name() {
    return this.assertLive(), this.data.name;
  }
  get lowerBound() {
    return this.assertLive(), this.data.lowerBound;
  }
  set lowerBound(value) {
    this.assertLive(), this.data.lowerBound = value;
  }
  get lower_bound() {
    return this.lowerBound;
  }
  set lower_bound(value) {
    this.lowerBound = value;
  }
  get upperBound() {
    return this.assertLive(), this.data.upperBound;
  }
  set upperBound(value) {
    this.assertLive(), this.data.upperBound = value;
  }
  get upper_bound() {
    return this.upperBound;
  }
  set upper_bound(value) {
    this.upperBound = value;
  }
  get integer() {
    return this.assertLive(), this.data.integer;
  }
  set integer(value) {
    this.assertLive(), this.data.integer = value;
  }
  get is_integer() {
    return this.integer;
  }
  set is_integer(value) {
    this.integer = value;
  }
  equals(other) {
    return this.model === other.model && this.id === other.id;
  }
  toString() {
    return this.assertLive(), this.name || `variable_${this.id}`;
  }
  assertLive() {
    if (this.data.deleted)
      throw new Error(`Variable ${this.id} has been deleted.`);
  }
}
class MathOptLinearConstraint {
  constructor(model, data) {
    __publicField(this, "model", model);
    __publicField(this, "data", data);
  }
  get id() {
    return this.data.id;
  }
  get name() {
    return this.assertLive(), this.data.name;
  }
  get lowerBound() {
    return this.assertLive(), this.data.lowerBound;
  }
  set lowerBound(value) {
    this.assertLive(), this.data.lowerBound = value;
  }
  get lower_bound() {
    return this.lowerBound;
  }
  set lower_bound(value) {
    this.lowerBound = value;
  }
  get upperBound() {
    return this.assertLive(), this.data.upperBound;
  }
  set upperBound(value) {
    this.assertLive(), this.data.upperBound = value;
  }
  get upper_bound() {
    return this.upperBound;
  }
  set upper_bound(value) {
    this.upperBound = value;
  }
  setCoefficient(variable, coefficient) {
    this.assertLive(), this.model.assertOwnsVariable(variable);
    const existingIndex = this.data.terms.findIndex((term2) => term2.variable.id === variable.id);
    if (coefficient === 0) {
      existingIndex >= 0 && this.data.terms.splice(existingIndex, 1);
      return;
    }
    const term = { variable, coefficient };
    existingIndex >= 0 ? this.data.terms[existingIndex] = term : this.data.terms.push(term);
  }
  set_coefficient(variable, coefficient) {
    this.setCoefficient(variable, coefficient);
  }
  getCoefficient(variable) {
    return this.assertLive(), this.model.assertOwnsVariable(variable), this.data.terms.find((term) => term.variable.id === variable.id)?.coefficient ?? 0;
  }
  get_coefficient(variable) {
    return this.getCoefficient(variable);
  }
  terms() {
    return this.assertLive(), [...this.data.terms].filter((term) => term.coefficient !== 0);
  }
  asBoundedLinearExpression() {
    return this.assertLive(), new MathOptBoundedExpression(
      this.lowerBound,
      new MathOptLinearExpression(this.terms()),
      this.upperBound
    );
  }
  as_bounded_linear_expression() {
    return this.asBoundedLinearExpression();
  }
  equals(other) {
    return this.model === other.model && this.id === other.id;
  }
  toString() {
    return this.assertLive(), this.name || `linear_constraint_${this.id}`;
  }
  assertLive() {
    if (this.data.deleted)
      throw new Error(`Linear constraint ${this.id} has been deleted.`);
  }
}
class MathOptIndicatorConstraint {
  constructor(model, data) {
    __publicField(this, "model", model);
    __publicField(this, "data", data);
  }
  get id() {
    return this.data.id;
  }
  get name() {
    return this.assertLive(), this.data.name;
  }
  get indicator() {
    return this.assertLive(), this.data.indicator;
  }
  get activateOnZero() {
    return this.assertLive(), this.data.activateOnZero;
  }
  get activate_on_zero() {
    return this.activateOnZero;
  }
  get lowerBound() {
    return this.assertLive(), this.data.lowerBound;
  }
  get lower_bound() {
    return this.lowerBound;
  }
  get upperBound() {
    return this.assertLive(), this.data.upperBound;
  }
  get upper_bound() {
    return this.upperBound;
  }
  terms() {
    return this.assertLive(), [...this.data.terms].filter((term) => term.coefficient !== 0);
  }
  assertLive() {
    if (this.data.deleted)
      throw new Error(`Indicator constraint ${this.id} has been deleted.`);
  }
}
class MathOptObjective {
  constructor(model) {
    __publicField(this, "model", model);
  }
  get isMaximize() {
    return this.model.objectiveData.maximize;
  }
  set isMaximize(value) {
    this.model.objectiveData = { ...this.model.objectiveData, maximize: value };
  }
  get is_maximize() {
    return this.isMaximize;
  }
  set is_maximize(value) {
    this.isMaximize = value;
  }
  get offset() {
    return this.model.objectiveData.offset;
  }
  set offset(value) {
    this.model.objectiveData = { ...this.model.objectiveData, offset: value };
  }
  get name() {
    return "";
  }
  clear() {
    this.model.objectiveData = { maximize: !1, linearTerms: [], quadraticTerms: [], offset: 0 };
  }
  setLinearCoefficient(variable, coefficient) {
    this.model.assertOwnsVariable(variable);
    const terms = this.model.objectiveData.linearTerms.filter((term) => term.variable.id !== variable.id);
    coefficient !== 0 && terms.push({ variable, coefficient }), this.model.objectiveData = { ...this.model.objectiveData, linearTerms: terms };
  }
  set_linear_coefficient(variable, coefficient) {
    this.setLinearCoefficient(variable, coefficient);
  }
  getLinearCoefficient(variable) {
    return this.model.assertOwnsVariable(variable), this.model.objectiveData.linearTerms.find((term) => term.variable.id === variable.id)?.coefficient ?? 0;
  }
  get_linear_coefficient(variable) {
    return this.getLinearCoefficient(variable);
  }
  linearTerms() {
    return [...this.model.objectiveData.linearTerms].filter((term) => term.coefficient !== 0);
  }
  linear_terms() {
    return this.linearTerms();
  }
  setQuadraticCoefficient(firstVariable, secondVariable, coefficient) {
    this.model.assertOwnsVariable(firstVariable), this.model.assertOwnsVariable(secondVariable);
    const key = new MathOptQuadraticTermKey(firstVariable, secondVariable), terms = this.model.objectiveData.quadraticTerms.filter((term) => !new MathOptQuadraticTermKey(term.firstVariable, term.secondVariable).equals(key));
    coefficient !== 0 && terms.push({ firstVariable: key.firstVariable, secondVariable: key.secondVariable, coefficient }), this.model.objectiveData = { ...this.model.objectiveData, quadraticTerms: terms };
  }
  set_quadratic_coefficient(firstVariable, secondVariable, coefficient) {
    this.setQuadraticCoefficient(firstVariable, secondVariable, coefficient);
  }
  getQuadraticCoefficient(firstVariable, secondVariable) {
    this.model.assertOwnsVariable(firstVariable), this.model.assertOwnsVariable(secondVariable);
    const key = new MathOptQuadraticTermKey(firstVariable, secondVariable);
    return this.model.objectiveData.quadraticTerms.find((term) => new MathOptQuadraticTermKey(term.firstVariable, term.secondVariable).equals(key))?.coefficient ?? 0;
  }
  get_quadratic_coefficient(firstVariable, secondVariable) {
    return this.getQuadraticCoefficient(firstVariable, secondVariable);
  }
  quadraticTerms() {
    return [...this.model.objectiveData.quadraticTerms].filter((term) => term.coefficient !== 0);
  }
  quadratic_terms() {
    return this.quadraticTerms();
  }
}
function findVariableKey(map, variable) {
  for (const key of map.keys())
    if (key.equals(variable)) return key;
}
function formatBound(value) {
  return value === Number.POSITIVE_INFINITY ? "inf" : value === Number.NEGATIVE_INFINITY ? "-inf" : Number.isInteger(value) ? `${value}.0` : String(value);
}
function formatExpressionNumber(value) {
  return Number.isInteger(value) ? `${value}.0` : String(value);
}
function formatSignedTerm(coefficient, body) {
  return ` ${coefficient < 0 ? "-" : "+"} ${formatExpressionNumber(Math.abs(coefficient))} * ${body}`;
}
function compareVariables(lhs, rhs) {
  return lhs.toString().localeCompare(rhs.toString()) || lhs.id - rhs.id;
}
function formatExpression(offset, linearTerms, quadraticTerms) {
  let result = formatExpressionNumber(offset);
  for (const term of [...linearTerms].filter((term2) => term2.coefficient !== 0).sort((lhs, rhs) => compareVariables(lhs.variable, rhs.variable)))
    result += formatSignedTerm(term.coefficient, term.variable.toString());
  for (const term of [...quadraticTerms].filter((term2) => term2.coefficient !== 0).sort((lhs, rhs) => compareVariables(lhs.firstVariable, rhs.firstVariable) || compareVariables(lhs.secondVariable, rhs.secondVariable)))
    result += formatSignedTerm(term.coefficient, `${term.firstVariable.toString()} * ${term.secondVariable.toString()}`);
  return result;
}
function findQuadraticKey(map, key) {
  for (const existing of map.keys())
    if (existing.equals(key)) return existing;
}
function linearTermEntries(expression) {
  return linearTermEntriesFromMap(expression.terms);
}
function linearTermEntriesFromMap(map) {
  return [...map.entries()].map(([variable, coefficient]) => ({ variable, coefficient }));
}
function readonlyMap(map) {
  return new Proxy(map, {
    get(target, property) {
      if (property === "set" || property === "delete" || property === "clear")
        return () => {
          throw new TypeError("ReadonlyMap does not support item assignment");
        };
      const value = Reflect.get(target, property, target);
      return typeof value == "function" ? value.bind(target) : value;
    }
  });
}
function quadraticTermEntries(expression) {
  return [...expression.quadraticTerms.entries()].map(([key, coefficient]) => ({
    firstVariable: key.firstVariable,
    secondVariable: key.secondVariable,
    coefficient
  }));
}
function isLinearTerm(input) {
  return typeof input == "object" && input !== null && "variable" in input && "coefficient" in input;
}
function isQuadraticTerm(input) {
  return typeof input == "object" && input !== null && "firstVariable" in input && "secondVariable" in input && "coefficient" in input;
}
function linearTerm(variable, coefficient = 1) {
  return { variable, coefficient };
}
function quadraticTerm(firstVariable, secondVariable, coefficient = 1) {
  return { firstVariable, secondVariable, coefficient };
}
function linearExpression(terms = [], offset = 0) {
  return new MathOptLinearExpression(terms, offset);
}
function quadraticExpression(linearTerms = [], quadraticTerms = [], offset = 0) {
  return new MathOptQuadraticExpression(linearTerms, quadraticTerms, offset);
}
function asFlatLinearExpression(input) {
  if (typeof input == "number") return new MathOptLinearExpression([], input);
  if (input instanceof MathOptLinearExpression) return input;
  if (input instanceof MathOptVariable) return new MathOptLinearExpression([{ variable: input, coefficient: 1 }]);
  if (isLinearTerm(input)) return new MathOptLinearExpression([input]);
  throw new TypeError("Unsupported MathOpt linear expression input.");
}
function asFlatQuadraticExpression(input) {
  if (input instanceof MathOptQuadraticExpression) return input;
  if (isQuadraticTerm(input)) return new MathOptQuadraticExpression([], [input]);
  const linear = asFlatLinearExpression(input);
  return new MathOptQuadraticExpression(linearTermEntries(linear), [], linear.offset);
}
function fastSum(inputs) {
  let linear = new MathOptLinearExpression(), quadratic = new MathOptQuadraticExpression(), hasQuadratic = !1;
  for (const input of inputs) {
    if (input instanceof MathOptQuadraticExpression || isQuadraticTerm(input)) {
      hasQuadratic = !0, quadratic = quadratic.add(input);
      continue;
    }
    hasQuadratic ? quadratic = quadratic.add(input) : linear = linear.add(input);
  }
  return hasQuadratic ? quadratic.add(linear) : linear;
}
function multiplyLinearExpressions(lhs, rhs) {
  const lhsFlat = asFlatLinearExpression(lhs), rhsFlat = asFlatLinearExpression(rhs), linearTerms = [], quadraticTerms = [];
  for (const term of linearTermEntries(lhsFlat)) {
    rhsFlat.offset !== 0 && linearTerms.push({
      variable: term.variable,
      coefficient: term.coefficient * rhsFlat.offset
    });
    for (const rhsTerm of linearTermEntries(rhsFlat))
      quadraticTerms.push({
        firstVariable: term.variable,
        secondVariable: rhsTerm.variable,
        coefficient: term.coefficient * rhsTerm.coefficient
      });
  }
  if (lhsFlat.offset !== 0)
    for (const term of linearTermEntries(rhsFlat))
      linearTerms.push({
        variable: term.variable,
        coefficient: lhsFlat.offset * term.coefficient
      });
  return new MathOptQuadraticExpression(linearTerms, quadraticTerms, lhsFlat.offset * rhsFlat.offset);
}
function evaluateExpression(expression, variableValues) {
  const values = (variable) => {
    if (variableValues instanceof Map) {
      const typedValues = variableValues, matchingVariable = findVariableKey(typedValues, variable);
      return typedValues.get(variable) ?? (matchingVariable ? typedValues.get(matchingVariable) : void 0) ?? 0;
    }
    const record = variableValues;
    return record[variable.id] ?? record[variable.name] ?? 0;
  }, flat = asFlatQuadraticExpression(expression);
  let result = flat.offset;
  for (const [variable, coefficient] of flat.linearTerms)
    result += coefficient * values(variable);
  for (const [key, coefficient] of flat.quadraticTerms)
    result += coefficient * values(key.firstVariable) * values(key.secondVariable);
  return result;
}
function boundedExpression(lowerBound, expression, upperBound) {
  return new MathOptBoundedExpression(lowerBound, expression, upperBound);
}
function lowerBoundedExpression(lowerBound, expression) {
  return new MathOptLowerBoundedExpression(lowerBound, expression);
}
function upperBoundedExpression(expression, upperBound) {
  return new MathOptUpperBoundedExpression(expression, upperBound);
}
function eq(lhs, rhs) {
  if (!isQuadraticExpressionInput(lhs) || !isQuadraticExpressionInput(rhs))
    throw new TypeError(`unsupported operand type(s) for ==: '${mathOptOperandType(lhs)}' and '${mathOptOperandType(rhs)}'`);
  if (typeof lhs == "number" && typeof rhs != "number")
    return boundedExpression(
      lhs,
      isQuadraticOnlyInput(rhs) ? asFlatQuadraticExpression(rhs) : asFlatLinearExpression(rhs),
      lhs
    );
  if (typeof rhs == "number")
    return boundedExpression(
      rhs,
      isQuadraticOnlyInput(lhs) ? asFlatQuadraticExpression(lhs) : asFlatLinearExpression(lhs),
      rhs
    );
  const expression = isQuadraticOnlyInput(lhs) || isQuadraticOnlyInput(rhs) ? isQuadraticOnlyInput(lhs) ? asFlatQuadraticExpression(lhs).subtract(rhs) : asFlatQuadraticExpression(rhs).subtract(lhs) : asFlatLinearExpression(lhs).subtract(rhs);
  return boundedExpression(0, expression, 0);
}
function ne(lhs, rhs) {
  throw new TypeError("!= constraints are not supported");
}
function variableEq(lhs, rhs) {
  return lhs === rhs ? !0 : lhs.model !== rhs.model ? !1 : lhs.id === rhs.id ? !0 : new MathOptVarEqVar(lhs, rhs);
}
function variableNe(lhs, rhs) {
  return variableEq(lhs, rhs) !== !0;
}
function isLinearExpressionInput(input) {
  return typeof input == "number" || input instanceof MathOptVariable || input instanceof MathOptLinearExpression || isLinearTerm(input);
}
function isQuadraticExpressionInput(input) {
  return isLinearExpressionInput(input) || input instanceof MathOptQuadraticExpression || isQuadraticTerm(input);
}
function isQuadraticOnlyInput(...inputs) {
  return inputs.some((input) => input instanceof MathOptQuadraticExpression || isQuadraticTerm(input));
}
function mathOptOperandType(input) {
  return input instanceof MathOptVariable ? "Variable" : input instanceof MathOptLinearExpression ? "LinearExpression" : input instanceof MathOptQuadraticExpression ? "QuadraticExpression" : input instanceof MathOptBoundedExpression ? "BoundedExpression" : input instanceof MathOptLowerBoundedExpression ? "LowerBoundedExpression" : input instanceof MathOptUpperBoundedExpression ? "UpperBoundedExpression" : isLinearTerm(input) ? "LinearTerm" : isQuadraticTerm(input) ? "QuadraticTerm" : typeof input == "string" ? "str" : typeof input;
}
function le(lhs, rhs) {
  if (lhs instanceof MathOptBoundedExpression || rhs instanceof MathOptBoundedExpression)
    throw new TypeError("Chained bounded expressions are ambiguous; use (a <= b) <= c with explicit completion helpers.");
  if (!isQuadraticExpressionInput(lhs) || !isQuadraticExpressionInput(rhs))
    throw new TypeError(`unsupported operand type(s) for <=: '${mathOptOperandType(lhs)}' and '${mathOptOperandType(rhs)}'`);
  return typeof lhs == "number" && typeof rhs != "number" ? lowerBoundedExpression(
    lhs,
    isQuadraticOnlyInput(rhs) ? asFlatQuadraticExpression(rhs) : asFlatLinearExpression(rhs)
  ) : typeof rhs == "number" ? upperBoundedExpression(
    isQuadraticOnlyInput(lhs) ? asFlatQuadraticExpression(lhs) : asFlatLinearExpression(lhs),
    rhs
  ) : isQuadraticOnlyInput(lhs) && !isQuadraticOnlyInput(rhs) ? boundedExpression(Number.NEGATIVE_INFINITY, asFlatQuadraticExpression(lhs).subtract(rhs), 0) : !isQuadraticOnlyInput(lhs) && isQuadraticOnlyInput(rhs) ? boundedExpression(0, asFlatQuadraticExpression(rhs).subtract(lhs), Number.POSITIVE_INFINITY) : boundedExpression(
    Number.NEGATIVE_INFINITY,
    isQuadraticOnlyInput(lhs, rhs) ? asFlatQuadraticExpression(lhs).subtract(rhs) : asFlatLinearExpression(lhs).subtract(rhs),
    0
  );
}
function ge(lhs, rhs) {
  if (lhs instanceof MathOptBoundedExpression || rhs instanceof MathOptBoundedExpression)
    throw new TypeError("Chained bounded expressions are ambiguous; use (a <= b) <= c with explicit completion helpers.");
  if (!isQuadraticExpressionInput(lhs) || !isQuadraticExpressionInput(rhs))
    throw new TypeError(`unsupported operand type(s) for >=: '${mathOptOperandType(lhs)}' and '${mathOptOperandType(rhs)}'`);
  return typeof lhs == "number" && typeof rhs != "number" ? upperBoundedExpression(
    isQuadraticOnlyInput(rhs) ? asFlatQuadraticExpression(rhs) : asFlatLinearExpression(rhs),
    lhs
  ) : typeof rhs == "number" ? lowerBoundedExpression(
    rhs,
    isQuadraticOnlyInput(lhs) ? asFlatQuadraticExpression(lhs) : asFlatLinearExpression(lhs)
  ) : isQuadraticOnlyInput(lhs) && !isQuadraticOnlyInput(rhs) ? boundedExpression(0, asFlatQuadraticExpression(lhs).subtract(rhs), Number.POSITIVE_INFINITY) : !isQuadraticOnlyInput(lhs) && isQuadraticOnlyInput(rhs) ? boundedExpression(Number.NEGATIVE_INFINITY, asFlatQuadraticExpression(rhs).subtract(lhs), 0) : boundedExpression(
    0,
    isQuadraticOnlyInput(lhs, rhs) ? asFlatQuadraticExpression(lhs).subtract(rhs) : asFlatLinearExpression(lhs).subtract(rhs),
    Number.POSITIVE_INFINITY
  );
}
function completeUpperBound(lowerBounded, upperBound) {
  if (!(lowerBounded instanceof MathOptLowerBoundedExpression))
    throw new TypeError(`unsupported operand type(s) for <=: '${mathOptOperandType(lowerBounded)}' and 'float'`);
  return lowerBounded.toBoundedExpression(upperBound);
}
function completeLowerBound(lowerBound, upperBounded) {
  if (!(upperBounded instanceof MathOptUpperBoundedExpression))
    throw new TypeError(`unsupported operand type(s) for >=: '${mathOptOperandType(upperBounded)}' and 'float'`);
  return upperBounded.toBoundedExpression(lowerBound);
}
async function initMathOpt() {
  if (shouldUseMathOptBridge()) {
    await initMathOptViaWorker();
    return;
  }
  await loadMathOptModule();
}
class MathOptIncrementalSolver {
  constructor(model, solverType = 3 /* GLOP */, options = {}) {
    __publicField(this, "model", model);
    __publicField(this, "solverType", solverType);
    __publicField(this, "options", options);
    __publicField(this, "initPromise");
    __publicField(this, "checkpoint");
    __publicField(this, "handle", null);
    __publicField(this, "closed", !1);
    __publicField(this, "useWorkerBridge", shouldUseMathOptBridge());
    this.checkpoint = model.snapshot(), (options.removeNames ?? options.remove_names ?? !1) || assertNoDuplicateNamesForIncrementalSolver(this.checkpoint), this.initPromise = this.create();
  }
  async create() {
    const requestBytes = MathOpt.encodeSolveRequest(this.model, {
      ...this.options,
      solverType: this.solverType
    }), responseBytes = this.useWorkerBridge ? await incrementalCreateViaWorker(requestBytes) : await incrementalCreateDirect(requestBytes), response = readMessage(responseBytes), statusBytes = response.messages.get(3)?.[0];
    if (statusBytes) {
      const status = readMessage(statusBytes);
      throw new Error(status.strings.get(2)?.[0] ?? "MathOpt incremental solver creation failed.");
    }
    const handleText = response.strings.get(2)?.[0], handle = handleText === void 0 ? 0 : Number(handleText);
    if (!Number.isInteger(handle) || handle <= 0)
      throw new Error("MathOpt incremental solver creation returned no solver handle.");
    return this.handle = handle, handle;
  }
  async solve(options = {}) {
    if (this.closed)
      throw new Error("MathOpt IncrementalSolver is closed.");
    const handle = await this.initPromise, mergedOptions = {
      ...this.options,
      ...options,
      solverType: this.solverType
    }, removeNames = mergedOptions.removeNames ?? mergedOptions.remove_names ?? !1, updateBytes = this.model.encodeModelUpdateSince(this.checkpoint, { removeNames }), requestBytes = MathOpt.encodeSolveRequest(this.model, mergedOptions), interrupterState = solveInterrupterState(mergedOptions), responseBytes = this.useWorkerBridge ? await incrementalSolveViaWorker(handle, requestBytes, updateBytes, interrupterState) : await incrementalSolveDirect(handle, requestBytes, updateBytes, interrupterState), result = decodeSolveResponse(responseBytes, this.model);
    this.checkpoint = this.model.snapshot();
    const messageCallback = solveMessageCallback(mergedOptions);
    return messageCallback && result.messages.length > 0 && messageCallback(result.messages), result;
  }
  async Solve(options = {}) {
    return this.solve(options);
  }
  async close() {
    if (!this.closed) {
      this.closed = !0;
      try {
        const handle = this.handle ?? await this.initPromise.catch(() => 0);
        handle > 0 && (this.useWorkerBridge ? await incrementalDeleteViaWorker(handle) : await incrementalDeleteDirect(handle));
      } finally {
        this.handle = null;
      }
    }
  }
}
const _MathOpt = class _MathOpt {
  static setWorkerBridgeEnabled(enabled) {
    setWorkerBridgeEnabled(enabled);
  }
  static isWorkerBridgeEnabled() {
    return isWorkerBridgeEnabled();
  }
  static Model(name = "") {
    return new MathOptModel(name);
  }
  static async solve(model, options = {}) {
    const requestBytes = _MathOpt.encodeSolveRequest(model, options), interrupterState = solveInterrupterState(options), responseBytes = shouldUseMathOptBridge() ? await solveViaWorker(requestBytes, interrupterState) : await solveDirect(requestBytes, interrupterState), result = decodeSolveResponse(responseBytes, model), messageCallback = solveMessageCallback(options);
    return messageCallback && result.messages.length > 0 && messageCallback(result.messages), result;
  }
  static encodeSolveRequest(model, options = {}) {
    return encodeSolveRequest(model, options);
  }
  static linearTerm(variable, coefficient = 1) {
    return linearTerm(variable, coefficient);
  }
  static quadraticTerm(firstVariable, secondVariable, coefficient = 1) {
    return quadraticTerm(firstVariable, secondVariable, coefficient);
  }
  static linearExpression(terms = [], offset = 0) {
    return linearExpression(terms, offset);
  }
  static quadraticExpression(linearTerms = [], quadraticTerms = [], offset = 0) {
    return quadraticExpression(linearTerms, quadraticTerms, offset);
  }
  static asFlatLinearExpression(input) {
    return asFlatLinearExpression(input);
  }
  static asFlatQuadraticExpression(input) {
    return asFlatQuadraticExpression(input);
  }
  static fastSum(inputs) {
    return fastSum(inputs);
  }
  static multiplyLinearExpressions(lhs, rhs) {
    return multiplyLinearExpressions(lhs, rhs);
  }
  static evaluateExpression(expression, variableValues) {
    return evaluateExpression(expression, variableValues);
  }
  static boundedExpression(lowerBound, expression, upperBound) {
    return boundedExpression(lowerBound, expression, upperBound);
  }
  static lowerBoundedExpression(lowerBound, expression) {
    return lowerBoundedExpression(lowerBound, expression);
  }
  static upperBoundedExpression(expression, upperBound) {
    return upperBoundedExpression(expression, upperBound);
  }
  static eq(lhs, rhs) {
    return eq(lhs, rhs);
  }
  static ne(lhs, rhs) {
    return ne(lhs, rhs);
  }
  static variableEq(lhs, rhs) {
    return variableEq(lhs, rhs);
  }
  static variableNe(lhs, rhs) {
    return variableNe(lhs, rhs);
  }
  static le(lhs, rhs) {
    return le(lhs, rhs);
  }
  static ge(lhs, rhs) {
    return ge(lhs, rhs);
  }
  static completeUpperBound(lowerBounded, upperBound) {
    return completeUpperBound(lowerBounded, upperBound);
  }
  static completeLowerBound(lowerBound, upperBounded) {
    return completeLowerBound(lowerBound, upperBounded);
  }
};
__publicField(_MathOpt, "SolverType", MathOptSolverType), __publicField(_MathOpt, "LPAlgorithm", MathOptLPAlgorithm), __publicField(_MathOpt, "Emphasis", MathOptEmphasis), __publicField(_MathOpt, "GScipEmphasis", GScipEmphasis), __publicField(_MathOpt, "GScipMetaParamValue", GScipMetaParamValue), __publicField(_MathOpt, "GScipParameters", GScipParameters), __publicField(_MathOpt, "GlopParameters", GlopParameters), __publicField(_MathOpt, "PdlpParameters", PdlpParameters), __publicField(_MathOpt, "PdlpOptimalityNorm", PdlpOptimalityNorm), __publicField(_MathOpt, "PdlpSchedulerType", PdlpSchedulerType), __publicField(_MathOpt, "PdlpRestartStrategy", PdlpRestartStrategy), __publicField(_MathOpt, "PdlpLinesearchRule", PdlpLinesearchRule), __publicField(_MathOpt, "GlpkParameters", GlpkParameters), __publicField(_MathOpt, "SolveInterrupter", MathOptSolveInterrupter), __publicField(_MathOpt, "SolveParameters", MathOptSolveParameters), __publicField(_MathOpt, "ModelSolveParameters", MathOptModelSolveParameters), __publicField(_MathOpt, "SparseVectorFilter", MathOptSparseVectorFilter), __publicField(_MathOpt, "SolutionHint", MathOptSolutionHint), __publicField(_MathOpt, "IncrementalSolver", MathOptIncrementalSolver), __publicField(_MathOpt, "LinearExpression", MathOptLinearExpression), __publicField(_MathOpt, "QuadraticExpression", MathOptQuadraticExpression), __publicField(_MathOpt, "QuadraticTermKey", MathOptQuadraticTermKey), __publicField(_MathOpt, "VarEqVar", MathOptVarEqVar), __publicField(_MathOpt, "BoundedExpression", MathOptBoundedExpression), __publicField(_MathOpt, "LowerBoundedExpression", MathOptLowerBoundedExpression), __publicField(_MathOpt, "UpperBoundedExpression", MathOptUpperBoundedExpression);
let MathOpt = _MathOpt;
async function initMathOptViaWorker() {
  await postWorkerRequest({
    type: "mathOptInit",
    id: nextWorkerBridgeRequestId()
  });
}
async function solveViaWorker(requestBytes, interrupterState) {
  const response = await postWorkerRequest({
    type: "mathOptSolve",
    id: nextWorkerBridgeRequestId(),
    requestBytes,
    useInterrupter: interrupterState.useInterrupter,
    interruptAtStart: interrupterState.interrupted
  });
  return new Uint8Array(response.bytes);
}
async function incrementalCreateViaWorker(requestBytes) {
  const response = await postWorkerRequest({
    type: "mathOptIncrementalCreate",
    id: nextWorkerBridgeRequestId(),
    requestBytes
  });
  return new Uint8Array(response.bytes);
}
async function incrementalSolveViaWorker(handle, requestBytes, updateBytes, interrupterState) {
  const response = await postWorkerRequest({
    type: "mathOptIncrementalSolve",
    id: nextWorkerBridgeRequestId(),
    handle,
    requestBytes,
    updateBytes: updateBytes ?? void 0,
    useInterrupter: interrupterState.useInterrupter,
    interruptAtStart: interrupterState.interrupted
  });
  return new Uint8Array(response.bytes);
}
async function incrementalDeleteViaWorker(handle) {
  await postWorkerRequest({
    type: "mathOptIncrementalDelete",
    id: nextWorkerBridgeRequestId(),
    handle
  });
}
async function solveDirect(requestBytes, interrupterState) {
  const module = await loadMathOptModule(), requestPtr = copyBytesToHeap(module, requestBytes), lenPtr = module._malloc(4);
  try {
    const ptr = await module.ccall(
      "mathopt_solve_request",
      "number",
      ["number", "number", "number", "number", "number"],
      [requestPtr, requestBytes.length, interrupterState.useInterrupter ? 1 : 0, interrupterState.interrupted ? 1 : 0, lenPtr],
      { async: !0 }
    ), length = new DataView(module.HEAPU8.buffer, lenPtr, 4).getUint32(0, !0), bytes = ptr && length > 0 ? new Uint8Array(module.HEAPU8.subarray(ptr, ptr + length)) : new Uint8Array();
    return ptr && module._free(ptr), bytes;
  } finally {
    requestPtr && module._free(requestPtr), module._free(lenPtr);
  }
}
async function incrementalCreateDirect(requestBytes) {
  const module = await loadMathOptModule(), requestPtr = copyBytesToHeap(module, requestBytes), lenPtr = module._malloc(4);
  try {
    const ptr = await module.ccall(
      "mathopt_incremental_create",
      "number",
      ["number", "number", "number"],
      [requestPtr, requestBytes.length, lenPtr],
      { async: !0 }
    ), length = new DataView(module.HEAPU8.buffer, lenPtr, 4).getUint32(0, !0), bytes = ptr && length > 0 ? new Uint8Array(module.HEAPU8.subarray(ptr, ptr + length)) : new Uint8Array();
    return ptr && module._free(ptr), bytes;
  } finally {
    requestPtr && module._free(requestPtr), module._free(lenPtr);
  }
}
async function incrementalSolveDirect(handle, requestBytes, updateBytes, interrupterState) {
  const module = await loadMathOptModule(), requestPtr = copyBytesToHeap(module, requestBytes), updatePtr = updateBytes ? copyBytesToHeap(module, updateBytes) : 0, lenPtr = module._malloc(4);
  try {
    const ptr = await module.ccall(
      "mathopt_incremental_solve",
      "number",
      ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
      [
        handle,
        requestPtr,
        requestBytes.length,
        updatePtr,
        updateBytes?.length ?? 0,
        updateBytes ? 1 : 0,
        interrupterState.useInterrupter ? 1 : 0,
        interrupterState.interrupted ? 1 : 0,
        lenPtr
      ],
      { async: !0 }
    ), length = new DataView(module.HEAPU8.buffer, lenPtr, 4).getUint32(0, !0), bytes = ptr && length > 0 ? new Uint8Array(module.HEAPU8.subarray(ptr, ptr + length)) : new Uint8Array();
    return ptr && module._free(ptr), bytes;
  } finally {
    requestPtr && module._free(requestPtr), updatePtr && module._free(updatePtr), module._free(lenPtr);
  }
}
async function incrementalDeleteDirect(handle) {
  await (await loadMathOptModule()).ccall("mathopt_incremental_delete", void 0, ["number"], [handle], { async: !0 });
}
function copyBytesToHeap(module, bytes) {
  if (bytes.length === 0) return 0;
  const ptr = module._malloc(bytes.length);
  return module.HEAPU8.set(bytes, ptr), ptr;
}
function encodeSolveRequest(model, options) {
  const solverType = typeof options.solverType == "string" ? MathOptSolverType[options.solverType] : options.solverType ?? 3 /* GLOP */;
  if (solverType === 6 /* GLPK */ && options.threads !== void 0 && options.threads !== 1)
    throw new Error("GLPK does not support multi-threaded MathOpt solves; use threads: 1 or omit threads.");
  const parameters = encodeMathOptSolveParameters(options), modelParameters = modelParametersBytes(options.modelParameters ?? options.model_parameters), removeNames = options.removeNames ?? options.remove_names ?? !1;
  return message([
    fieldVarint(1, solverType),
    fieldMessage(2, model.encodeModelProto({ removeNames })),
    fieldMessageIfPresent(4, parameters),
    fieldMessageIfPresent(5, modelParameters)
  ]);
}
function encodeMathOptSolveParameters(options) {
  const raw = options.parameters ?? options.solveParameters ?? options.solve_parameters;
  if (raw) return solveParametersBytes(raw);
  const enableOutput = options.enableOutput ?? options.enable_output ?? (solveMessageCallback(options) ? !0 : void 0), fields = [
    fieldDurationSeconds(1, options.timeLimitSeconds ?? options.time_limit_seconds),
    optionalVarintField(2, options.iterationLimit ?? options.iteration_limit),
    optionalBoolField(3, enableOutput),
    optionalVarintField(4, options.threads),
    optionalVarintField(5, options.randomSeed ?? options.random_seed),
    enumField(6, options.lpAlgorithm ?? options.lp_algorithm, MathOptLPAlgorithm),
    enumField(7, options.presolve, MathOptEmphasis),
    enumField(8, options.cuts, MathOptEmphasis),
    enumField(9, options.heuristics, MathOptEmphasis),
    enumField(10, options.scaling, MathOptEmphasis),
    fieldMessageIfPresent(12, backendParametersBytes(options.gscip, GScipParameters)),
    fieldMessageIfPresent(14, backendParametersBytes(options.glop, GlopParameters)),
    fieldMessageIfPresent(15, encodeSatParameters(options.cpSat ?? options.cp_sat)),
    fieldMessageIfPresent(16, backendParametersBytes(options.pdlp, PdlpParameters)),
    optionalDoubleField(17, options.relativeGapTolerance ?? options.relative_gap_tolerance),
    optionalDoubleField(18, options.absoluteGapTolerance ?? options.absolute_gap_tolerance),
    optionalDoubleField(20, options.cutoffLimit ?? options.cutoff_limit),
    optionalDoubleField(21, options.objectiveLimit ?? options.objective_limit),
    optionalDoubleField(22, options.bestBoundLimit ?? options.best_bound_limit),
    optionalVarintField(23, options.solutionLimit ?? options.solution_limit),
    optionalVarintField(24, options.nodeLimit ?? options.node_limit),
    optionalVarintField(25, options.solutionPoolSize ?? options.solution_pool_size),
    fieldMessageIfPresent(26, backendParametersBytes(options.glpk, GlpkParameters))
  ], encoded = message(fields);
  return encoded.length > 0 ? encoded : null;
}
function objectiveData(maximize, terms, offset) {
  const expression = Array.isArray(terms) ? new MathOptLinearExpression(terms, offset) : asFlatQuadraticExpression(terms).add(offset);
  return expression instanceof MathOptLinearExpression ? {
    maximize,
    linearTerms: linearTermEntries(expression),
    quadraticTerms: [],
    offset: expression.offset
  } : {
    maximize,
    linearTerms: linearTermEntriesFromMap(expression.linearTerms),
    quadraticTerms: quadraticTermEntries(expression),
    offset: expression.offset
  };
}
function linearObjectiveData(maximize, terms, offset) {
  const expression = Array.isArray(terms) ? new MathOptLinearExpression(terms, offset) : asFlatLinearExpression(terms).add(offset);
  return {
    maximize,
    linearTerms: linearTermEntries(expression),
    quadraticTerms: [],
    offset: expression.offset
  };
}
function encodeSparseDoubleVector(terms) {
  const sortedTerms = [...terms].sort((a, b) => a.variable.id - b.variable.id);
  return message([
    fieldPackedVarints(1, sortedTerms.map((term) => term.variable.id)),
    fieldPackedDoubles(2, sortedTerms.map((term) => term.coefficient))
  ]);
}
function encodeLinearConstraintDoubleVector(terms) {
  const sortedTerms = [...terms].sort((a, b) => a.linearConstraint.id - b.linearConstraint.id);
  return message([
    fieldPackedVarints(1, sortedTerms.map((term) => term.linearConstraint.id)),
    fieldPackedDoubles(2, sortedTerms.map((term) => term.value))
  ]);
}
function encodeVariableInt32Vector(terms) {
  const sortedTerms = [...terms].sort((a, b) => a.variable.id - b.variable.id);
  return message([
    fieldPackedVarints(1, sortedTerms.map((term) => term.variable.id)),
    fieldPackedVarints(2, sortedTerms.map((term) => term.priority))
  ]);
}
function encodeSparseDoubleMatrix(terms) {
  const sortedTerms = [...terms].sort((a, b) => a.rowId - b.rowId || a.columnId - b.columnId);
  return message([
    fieldPackedVarints(1, sortedTerms.map((term) => term.rowId)),
    fieldPackedVarints(2, sortedTerms.map((term) => term.columnId)),
    fieldPackedDoubles(3, sortedTerms.map((term) => term.coefficient))
  ]);
}
function encodeModelUpdate(model, snapshot, options = {}) {
  const current = model.snapshot(), previousVariables = new Map(snapshot.variables.map((variable) => [variable.id, variable])), currentVariables = new Map(current.variables.map((variable) => [variable.id, variable])), previousConstraints = new Map(snapshot.linearConstraints.map((constraint) => [constraint.id, constraint])), currentConstraints = new Map(current.linearConstraints.map((constraint) => [constraint.id, constraint])), previousIndicators = new Map(snapshot.indicatorConstraints.map((constraint) => [constraint.id, constraint])), currentIndicators = new Map(current.indicatorConstraints.map((constraint) => [constraint.id, constraint])), deletedVariableIds = snapshot.variables.filter((variable) => !variable.deleted && currentVariables.get(variable.id)?.deleted).map((variable) => variable.id), deletedLinearConstraintIds = snapshot.linearConstraints.filter((constraint) => !constraint.deleted && currentConstraints.get(constraint.id)?.deleted).map((constraint) => constraint.id), deletedIndicatorConstraintIds = snapshot.indicatorConstraints.filter((constraint) => !constraint.deleted && currentIndicators.get(constraint.id)?.deleted).map((constraint) => constraint.id), newVariables = current.variables.filter((variable) => {
    const previous = previousVariables.get(variable.id);
    return !variable.deleted && (!previous || previous.deleted);
  }), newLinearConstraints = current.linearConstraints.filter((constraint) => {
    const previous = previousConstraints.get(constraint.id);
    return !constraint.deleted && (!previous || previous.deleted);
  }), newIndicatorConstraints = current.indicatorConstraints.filter((constraint) => {
    const previous = previousIndicators.get(constraint.id);
    return !constraint.deleted && (!previous || previous.deleted);
  }), variableLowerUpdates = changedValues(snapshot.variables, current.variables, (item) => item.lowerBound), variableUpperUpdates = changedValues(snapshot.variables, current.variables, (item) => item.upperBound), variableIntegerUpdates = changedValues(snapshot.variables, current.variables, (item) => item.integer), linearLowerUpdates = changedValues(snapshot.linearConstraints, current.linearConstraints, (item) => item.lowerBound), linearUpperUpdates = changedValues(snapshot.linearConstraints, current.linearConstraints, (item) => item.upperBound), matrixUpdates = changedMatrixEntries(snapshot.linearConstraints, current.linearConstraints), objectiveUpdate = encodeObjectiveUpdate(snapshot.objective, current.objective), indicatorUpdate = message([
    deletedIndicatorConstraintIds.length ? fieldPackedVarints(1, deletedIndicatorConstraintIds.sort((a, b) => a - b)) : empty(),
    ...newIndicatorConstraints.map((constraint) => fieldMessage(2, message([
      fieldVarint(1, constraint.id),
      fieldMessage(2, encodeIndicatorConstraintSnapshot(constraint, options))
    ])))
  ]), encoded = message([
    deletedVariableIds.length ? fieldPackedVarints(1, deletedVariableIds.sort((a, b) => a - b)) : empty(),
    deletedLinearConstraintIds.length ? fieldPackedVarints(2, deletedLinearConstraintIds.sort((a, b) => a - b)) : empty(),
    fieldMessageIfPresent(3, message([
      vectorUpdate(1, variableLowerUpdates, fieldPackedDoubles),
      vectorUpdate(2, variableUpperUpdates, fieldPackedDoubles),
      vectorUpdate(3, variableIntegerUpdates, fieldPackedBools)
    ])),
    fieldMessageIfPresent(4, message([
      vectorUpdate(1, linearLowerUpdates, fieldPackedDoubles),
      vectorUpdate(2, linearUpperUpdates, fieldPackedDoubles)
    ])),
    fieldMessageIfPresent(5, encodeVariablesSnapshot(newVariables, options)),
    fieldMessageIfPresent(6, encodeLinearConstraintsSnapshot(newLinearConstraints, options)),
    fieldMessageIfPresent(7, objectiveUpdate),
    fieldMessageIfPresent(8, matrixUpdates.length ? encodeSparseDoubleMatrix(matrixUpdates) : null),
    fieldMessageIfPresent(12, indicatorUpdate.length ? indicatorUpdate : null)
  ]);
  return encoded.length > 0 ? encoded : null;
}
function assertNoDuplicateNamesForIncrementalSolver(snapshot) {
  const seen = /* @__PURE__ */ new Set();
  for (const name of [
    ...snapshot.variables.filter((variable) => !variable.deleted).map((variable) => variable.name),
    ...snapshot.linearConstraints.filter((constraint) => !constraint.deleted).map((constraint) => constraint.name),
    ...snapshot.indicatorConstraints.filter((constraint) => !constraint.deleted).map((constraint) => constraint.name)
  ])
    if (name !== "") {
      if (seen.has(name))
        throw new Error(`duplicate name: ${name}`);
      seen.add(name);
    }
}
function encodeVariablesSnapshot(variables, options = {}) {
  const active = [...variables].filter((variable) => !variable.deleted).sort((a, b) => a.id - b.id);
  return active.length === 0 ? null : message([
    fieldPackedVarints(1, active.map((variable) => variable.id)),
    fieldPackedDoubles(2, active.map((variable) => variable.lowerBound)),
    fieldPackedDoubles(3, active.map((variable) => variable.upperBound)),
    fieldPackedBools(4, active.map((variable) => variable.integer)),
    ...options.removeNames ? [] : active.map((variable) => fieldString(5, variable.name))
  ]);
}
function encodeLinearConstraintsSnapshot(constraints, options = {}) {
  const active = [...constraints].filter((constraint) => !constraint.deleted).sort((a, b) => a.id - b.id);
  return active.length === 0 ? null : message([
    fieldPackedVarints(1, active.map((constraint) => constraint.id)),
    fieldPackedDoubles(2, active.map((constraint) => constraint.lowerBound)),
    fieldPackedDoubles(3, active.map((constraint) => constraint.upperBound)),
    ...options.removeNames ? [] : active.map((constraint) => fieldString(4, constraint.name))
  ]);
}
function encodeIndicatorConstraintSnapshot(constraint, options = {}) {
  return message([
    constraint.indicatorId === void 0 ? empty() : fieldVarint(1, constraint.indicatorId),
    constraint.activateOnZero ? fieldBool(6, !0) : empty(),
    fieldMessage(2, encodeSparseDoubleVectorById(constraint.terms)),
    fieldDouble(3, constraint.lowerBound),
    fieldDouble(4, constraint.upperBound),
    options.removeNames ? empty() : fieldString(5, constraint.name)
  ]);
}
function encodeSparseDoubleVectorById(terms) {
  const sortedTerms = [...terms].filter((term) => term.coefficient !== 0).sort((a, b) => a.variableId - b.variableId);
  return message([
    fieldPackedVarints(1, sortedTerms.map((term) => term.variableId)),
    fieldPackedDoubles(2, sortedTerms.map((term) => term.coefficient))
  ]);
}
function changedValues(previous, current, value) {
  const currentById = new Map(current.map((item) => [item.id, item]));
  return previous.flatMap((oldItem) => {
    if (oldItem.deleted) return [];
    const newItem = currentById.get(oldItem.id);
    return !newItem || newItem.deleted ? [] : Object.is(value(oldItem), value(newItem)) ? [] : [{ id: oldItem.id, value: value(newItem) }];
  });
}
function vectorUpdate(field, updates, encodeValues) {
  if (updates.length === 0) return empty();
  const sorted = [...updates].sort((a, b) => a.id - b.id);
  return fieldMessage(field, message([
    fieldPackedVarints(1, sorted.map((update) => update.id)),
    encodeValues(2, sorted.map((update) => update.value))
  ]));
}
function changedMatrixEntries(previous, current) {
  const previousById = new Map(previous.map((constraint) => [constraint.id, constraint])), updates = [];
  for (const constraint of current) {
    if (constraint.deleted) continue;
    const previousConstraint = previousById.get(constraint.id), previousTerms = termsByVariableId(previousConstraint && !previousConstraint.deleted ? previousConstraint.terms : []), currentTerms = termsByVariableId(constraint.terms), variableIds = /* @__PURE__ */ new Set([...previousTerms.keys(), ...currentTerms.keys()]);
    for (const variableId of variableIds) {
      const oldCoefficient = previousTerms.get(variableId) ?? 0, newCoefficient = currentTerms.get(variableId) ?? 0;
      Object.is(oldCoefficient, newCoefficient) || updates.push({ rowId: constraint.id, columnId: variableId, coefficient: newCoefficient });
    }
  }
  return updates;
}
function termsByVariableId(terms) {
  const result = /* @__PURE__ */ new Map();
  for (const term of terms)
    result.set(term.variableId, (result.get(term.variableId) ?? 0) + term.coefficient);
  return result;
}
function encodeObjectiveUpdate(previous, current) {
  const linearUpdates = changedTermMap(
    previous.linearTerms.map((term) => [term.variableId, term.coefficient]),
    current.linearTerms.map((term) => [term.variableId, term.coefficient])
  ), quadraticUpdates = changedQuadraticTermMap(previous.quadraticTerms, current.quadraticTerms), encoded = message([
    previous.maximize === current.maximize ? empty() : fieldBool(1, current.maximize),
    Object.is(previous.offset, current.offset) ? empty() : fieldDouble(2, current.offset),
    fieldMessageIfPresent(3, linearUpdates.length ? encodeSparseDoubleVectorById(
      linearUpdates.map((term) => ({ variableId: term.id, coefficient: term.coefficient }))
    ) : null),
    fieldMessageIfPresent(4, quadraticUpdates.length ? encodeSparseDoubleMatrix(
      quadraticUpdates.map((term) => ({ rowId: term.firstVariableId, columnId: term.secondVariableId, coefficient: term.coefficient }))
    ) : null)
  ]);
  return encoded.length > 0 ? encoded : null;
}
function changedTermMap(previousEntries, currentEntries) {
  const previous = new Map(previousEntries), current = new Map(currentEntries), ids = /* @__PURE__ */ new Set([...previous.keys(), ...current.keys()]), updates = [];
  for (const id of ids) {
    const oldCoefficient = previous.get(id) ?? 0, newCoefficient = current.get(id) ?? 0;
    Object.is(oldCoefficient, newCoefficient) || updates.push({ id, coefficient: newCoefficient });
  }
  return updates;
}
function changedQuadraticTermMap(previousTerms, currentTerms) {
  const key = (term) => `${term.firstVariableId}:${term.secondVariableId}`, previous = new Map(previousTerms.map((term) => [key(term), term])), current = new Map(currentTerms.map((term) => [key(term), term])), keys = /* @__PURE__ */ new Set([...previous.keys(), ...current.keys()]), updates = [];
  for (const termKey of keys) {
    const oldTerm = previous.get(termKey), coefficient = current.get(termKey)?.coefficient ?? 0;
    if (!Object.is(oldTerm?.coefficient ?? 0, coefficient)) {
      const [firstVariableId, secondVariableId] = termKey.split(":").map(Number);
      updates.push({ firstVariableId, secondVariableId, coefficient });
    }
  }
  return updates;
}
function decodeSolveResponse(bytes, model) {
  const response = readMessage(bytes), messages = response.strings.get(2) ?? [], statusBytes = response.messages.get(3)?.[0];
  if (statusBytes) {
    const messageText = readMessage(statusBytes).strings.get(2)?.[0] ?? "MathOpt solve failed.";
    throw new Error(messageText);
  }
  const resultBytes = response.messages.get(1)?.[0];
  if (!resultBytes)
    throw new Error("MathOpt solve returned no result.");
  const result = readMessage(resultBytes), termination = result.messages.get(2)?.[0], terminationMessage = termination ? readMessage(termination) : void 0, terminationReasonNumber = terminationMessage ? Number(terminationMessage.varints.get(1)?.[0] ?? 0n) : 0, terminationLimitNumber = terminationMessage ? Number(terminationMessage.varints.get(2)?.[0] ?? 0n) : 0, objectiveBounds = terminationMessage?.messages.get(5)?.[0], objectiveBoundsMessage = objectiveBounds ? readMessage(objectiveBounds) : void 0, solveStatsBytes = result.messages.get(6)?.[0], solveStats = solveStatsBytes ? readMessage(solveStatsBytes) : void 0, primalBound = objectiveBoundsMessage?.doubles.get(2)?.[0] ?? solveStats?.doubles.get(2)?.[0] ?? null, dualBound = objectiveBoundsMessage?.doubles.get(3)?.[0] ?? solveStats?.doubles.get(3)?.[0] ?? null, problemStatusBytes = terminationMessage?.messages.get(4)?.[0], statsProblemStatusBytes = solveStats?.messages.get(4)?.[0], problemStatusMessage = problemStatusBytes ? readMessage(problemStatusBytes) : statsProblemStatusBytes ? readMessage(statsProblemStatusBytes) : void 0, primalStatus = Number(problemStatusMessage?.varints.get(1)?.[0] ?? 0n), dualStatus = Number(problemStatusMessage?.varints.get(2)?.[0] ?? 0n), primalOrDualInfeasible = !!Number(problemStatusMessage?.varints.get(3)?.[0] ?? 0n), solveTime = solveStats?.messages.get(1)?.[0], solveTimeSeconds = solveTime ? decodeDurationSeconds(solveTime) : null, solutions = (result.messages.get(3) ?? []).map((solutionBytes) => decodeSolution(solutionBytes, model)), primalRays = (result.messages.get(4) ?? []).map((rayBytes) => decodePrimalRay(rayBytes, model)), dualRays = (result.messages.get(5) ?? []).map((rayBytes) => decodeDualRay(rayBytes, model)), firstPrimalSolution = solutions.find((solution) => solution.primalSolution !== null)?.primalSolution ?? null, bestSolution = solutions[0] ?? null, firstDualRay = dualRays[0] ?? null, firstPrimalRay = primalRays[0] ?? null, objectiveValue = firstPrimalSolution?.objectiveValue ?? null, variableValues = firstPrimalSolution?.variableValues ?? {}, variableValuesById = firstPrimalSolution?.variableValuesById ?? {};
  return {
    terminationReason: terminationReasonNames[terminationReasonNumber] ?? `TERMINATION_REASON_${terminationReasonNumber}`,
    terminationLimit: terminationLimitNumber === 0 ? null : terminationLimitNames[terminationLimitNumber] ?? `LIMIT_${terminationLimitNumber}`,
    solveTimeSeconds,
    primalBound,
    dualBound,
    primalStatus: problemStatusMessage ? feasibilityStatusNames[primalStatus] ?? `FEASIBILITY_STATUS_${primalStatus}` : null,
    dualStatus: problemStatusMessage ? feasibilityStatusNames[dualStatus] ?? `FEASIBILITY_STATUS_${dualStatus}` : null,
    primalOrDualInfeasible,
    objectiveValue,
    variableValues,
    variableValuesById,
    solutions,
    primalRays,
    dualRays,
    messages,
    rawResponse: bytes,
    solve_time() {
      return solveTimeSeconds;
    },
    best_objective_bound() {
      return dualBound;
    },
    has_primal_feasible_solution() {
      return firstPrimalSolution?.feasibilityStatus === "SOLUTION_STATUS_FEASIBLE";
    },
    has_dual_feasible_solution() {
      return bestSolution?.dualSolution?.feasibilityStatus === "SOLUTION_STATUS_FEASIBLE";
    },
    has_ray() {
      return firstPrimalRay !== null;
    },
    has_dual_ray() {
      return firstDualRay !== null;
    },
    has_basis() {
      return bestSolution?.basis !== null && bestSolution?.basis !== void 0;
    },
    bounded() {
      return primalStatus === 2 && dualStatus === 2 && !primalOrDualInfeasible;
    },
    objective_value() {
      if (objectiveValue === null || firstPrimalSolution?.feasibilityStatus !== "SOLUTION_STATUS_FEASIBLE")
        throw new Error("MathOpt solve result has no primal feasible solution.");
      return objectiveValue;
    },
    variable_values: ((input) => {
      if (firstPrimalSolution?.feasibilityStatus !== "SOLUTION_STATUS_FEASIBLE")
        throw new Error("MathOpt solve result has no primal feasible solution.");
      return input === void 0 ? variableValues : Array.isArray(input) ? input.map((variable) => variableValueForResult(model, firstPrimalSolution, variable)) : variableValueForResult(model, firstPrimalSolution, input);
    }),
    reduced_costs: ((input) => {
      const dualSolution = bestSolution?.dualSolution ?? null;
      if (dualSolution?.feasibilityStatus !== "SOLUTION_STATUS_FEASIBLE")
        throw new Error("Best solution does not have a dual feasible solution.");
      return variableMapAccessor(model, dualSolution.reducedCosts, dualSolution.reducedCostsById, input, "reduced_costs");
    }),
    dual_values: ((input) => {
      const dualSolution = bestSolution?.dualSolution ?? null;
      if (dualSolution?.feasibilityStatus !== "SOLUTION_STATUS_FEASIBLE")
        throw new Error("Best solution does not have a dual feasible solution.");
      return constraintMapAccessor(model, dualSolution.dualValues, dualSolution.dualValuesById, input, "dual_values");
    }),
    ray_variable_values: ((input) => {
      if (firstPrimalRay === null)
        throw new Error("MathOpt solve result has no primal ray.");
      return variableMapAccessor(model, firstPrimalRay.variableValues, firstPrimalRay.variableValuesById, input, "ray_variable_values");
    }),
    ray_reduced_costs: ((input) => {
      if (firstDualRay === null)
        throw new Error("MathOpt solve result has no dual ray.");
      return variableMapAccessor(model, firstDualRay.reducedCosts, firstDualRay.reducedCostsById, input, "ray_reduced_costs");
    }),
    ray_dual_values: ((input) => {
      if (firstDualRay === null)
        throw new Error("MathOpt solve result has no dual ray.");
      return constraintMapAccessor(model, firstDualRay.dualValues, firstDualRay.dualValuesById, input, "ray_dual_values");
    }),
    variable_status: ((input) => {
      const basis = bestSolution?.basis ?? null;
      if (basis === null)
        throw new Error("Best solution does not have a basis.");
      return variableMapAccessor(model, basis.variableStatus, basis.variableStatusById, input, "variable_status");
    }),
    constraint_status: ((input) => {
      const basis = bestSolution?.basis ?? null;
      if (basis === null)
        throw new Error("Best solution does not have a basis.");
      return constraintMapAccessor(model, basis.constraintStatus, basis.constraintStatusById, input, "constraint_status");
    })
  };
}
function variableValueForResult(model, solution, variable) {
  if (!(variable instanceof MathOptVariable))
    throw new Error("MathOpt variable_values() expects a MathOptVariable or an array of MathOptVariable.");
  if (variable.model !== model)
    throw new Error("Variable belongs to a different MathOpt model.");
  if (variable.assertLive(), !(variable.id in solution.variableValuesById))
    throw new Error(`Variable ${variable.toString()} is not present in MathOpt variable_values().`);
  return solution.variableValuesById[variable.id];
}
function variableMapAccessor(model, byName, byId, input, methodName) {
  return input === void 0 ? byName : Array.isArray(input) ? input.map((variable) => variableValueFromMap(model, byId, variable, methodName)) : variableValueFromMap(model, byId, input, methodName);
}
function variableValueFromMap(model, byId, variable, methodName) {
  if (!(variable instanceof MathOptVariable))
    throw new Error(`MathOpt ${methodName}() expects a MathOptVariable or an array of MathOptVariable.`);
  if (variable.model !== model)
    throw new Error(`Variable ${variable.toString()} belongs to a different MathOpt model.`);
  if (variable.assertLive(), !(variable.id in byId))
    throw new Error(`Variable ${variable.toString()} is not present in MathOpt ${methodName}().`);
  return byId[variable.id];
}
function constraintMapAccessor(model, byName, byId, input, methodName) {
  return input === void 0 ? byName : Array.isArray(input) ? input.map((constraint) => constraintValueFromMap(model, byId, constraint, methodName)) : constraintValueFromMap(model, byId, input, methodName);
}
function constraintValueFromMap(model, byId, constraint, methodName) {
  if (!(constraint instanceof MathOptLinearConstraint))
    throw new Error(`MathOpt ${methodName}() expects a MathOptLinearConstraint or an array of MathOptLinearConstraint.`);
  if (constraint.model !== model)
    throw new Error(`Linear constraint ${constraint.toString()} belongs to a different MathOpt model.`);
  if (constraint.assertLive(), !(constraint.id in byId))
    throw new Error(`Linear constraint ${constraint.toString()} is not present in MathOpt ${methodName}().`);
  return byId[constraint.id];
}
function decodeSolution(bytes, model) {
  const solution = readMessage(bytes), primalBytes = solution.messages.get(1)?.[0], dualBytes = solution.messages.get(2)?.[0], basisBytes = solution.messages.get(3)?.[0];
  return {
    primalSolution: primalBytes ? decodePrimalSolution(primalBytes, model) : null,
    dualSolution: dualBytes ? decodeDualSolution(dualBytes, model) : null,
    basis: basisBytes ? decodeBasis(basisBytes, model) : null
  };
}
function decodePrimalSolution(bytes, model) {
  const primal = readMessage(bytes), variableValues = decodeSparseDoubleVector(
    primal.messages.get(1)?.[0],
    (id) => model.variableName(id)
  );
  return {
    objectiveValue: primal.doubles.get(2)?.[0] ?? null,
    variableValues: variableValues.byName,
    variableValuesById: variableValues.byId,
    feasibilityStatus: solutionStatusNames[Number(primal.varints.get(3)?.[0] ?? 0n)] ?? `SOLUTION_STATUS_${Number(primal.varints.get(3)?.[0] ?? 0n)}`
  };
}
function decodeDualSolution(bytes, model) {
  const dual = readMessage(bytes), dualValues = decodeSparseDoubleVector(
    dual.messages.get(1)?.[0],
    (id) => model.linearConstraintName(id)
  ), reducedCosts = decodeSparseDoubleVector(
    dual.messages.get(2)?.[0],
    (id) => model.variableName(id)
  );
  return {
    objectiveValue: dual.doubles.get(3)?.[0] ?? null,
    dualValues: dualValues.byName,
    dualValuesById: dualValues.byId,
    reducedCosts: reducedCosts.byName,
    reducedCostsById: reducedCosts.byId,
    feasibilityStatus: solutionStatusNames[Number(dual.varints.get(4)?.[0] ?? 0n)] ?? `SOLUTION_STATUS_${Number(dual.varints.get(4)?.[0] ?? 0n)}`
  };
}
function decodePrimalRay(bytes, model) {
  const ray = readMessage(bytes), variableValues = decodeSparseDoubleVector(
    ray.messages.get(1)?.[0],
    (id) => model.variableName(id)
  );
  return {
    variableValues: variableValues.byName,
    variableValuesById: variableValues.byId
  };
}
function decodeDualRay(bytes, model) {
  const ray = readMessage(bytes), dualValues = decodeSparseDoubleVector(
    ray.messages.get(1)?.[0],
    (id) => model.linearConstraintName(id)
  ), reducedCosts = decodeSparseDoubleVector(
    ray.messages.get(2)?.[0],
    (id) => model.variableName(id)
  );
  return {
    dualValues: dualValues.byName,
    dualValuesById: dualValues.byId,
    reducedCosts: reducedCosts.byName,
    reducedCostsById: reducedCosts.byId
  };
}
function decodeBasis(bytes, model) {
  const basis = readMessage(bytes), constraintStatus = decodeSparseBasisStatusVector(
    basis.messages.get(1)?.[0],
    (id) => model.linearConstraintName(id)
  ), variableStatus = decodeSparseBasisStatusVector(
    basis.messages.get(2)?.[0],
    (id) => model.variableName(id)
  ), basicDualFeasibilityNumber = Number(basis.varints.get(3)?.[0] ?? 0n);
  return {
    variableStatus: variableStatus.byName,
    variableStatusById: variableStatus.byId,
    constraintStatus: constraintStatus.byName,
    constraintStatusById: constraintStatus.byId,
    basicDualFeasibility: solutionStatusNames[basicDualFeasibilityNumber] ?? `SOLUTION_STATUS_${basicDualFeasibilityNumber}`
  };
}
function decodeDurationSeconds(bytes) {
  const duration = readMessage(bytes), seconds = Number(duration.varints.get(1)?.[0] ?? 0n), nanos = Number(duration.varints.get(2)?.[0] ?? 0n);
  return seconds + nanos / 1e9;
}
function decodeSparseBasisStatusVector(bytes, nameForId) {
  const byId = {}, byName = {};
  if (!bytes) return { byId, byName };
  const sparse = readMessage(bytes), ids = sparse.packedVarints.get(1) ?? [], values = sparse.packedVarints.get(2) ?? [];
  return ids.forEach((id, index) => {
    const numericId = Number(id), statusNumber = Number(values[index] ?? 0n), status = basisStatusNames[statusNumber] ?? `BASIS_STATUS_${statusNumber}`;
    byId[numericId] = status, byName[nameForId(numericId)] = status;
  }), { byId, byName };
}
function decodeSparseDoubleVector(bytes, nameForId) {
  const byId = {}, byName = {};
  if (!bytes) return { byId, byName };
  const sparse = readMessage(bytes), ids = sparse.packedVarints.get(1) ?? [], values = sparse.packedDoubles.get(2) ?? [];
  return ids.forEach((id, index) => {
    const numericId = Number(id), value = values[index] ?? 0;
    byId[numericId] = value, byName[nameForId(numericId)] = value;
  }), { byId, byName };
}
function readMessage(bytes) {
  const decoded = {
    varints: /* @__PURE__ */ new Map(),
    strings: /* @__PURE__ */ new Map(),
    doubles: /* @__PURE__ */ new Map(),
    messages: /* @__PURE__ */ new Map(),
    packedVarints: /* @__PURE__ */ new Map(),
    packedDoubles: /* @__PURE__ */ new Map()
  };
  let offset = 0;
  for (; offset < bytes.length; ) {
    const key = readVarint(bytes, offset);
    offset = key.offset;
    const field = Number(key.value >> 3n), wire = Number(key.value & 7n);
    if (wire === 0) {
      const value = readVarint(bytes, offset);
      offset = value.offset, pushMap(decoded.varints, field, value.value);
    } else if (wire === 1) {
      const value = new DataView(bytes.buffer, bytes.byteOffset + offset, 8).getFloat64(0, !0);
      offset += 8, pushMap(decoded.doubles, field, value);
    } else if (wire === 2) {
      const length = readVarint(bytes, offset);
      offset = length.offset;
      const end = offset + Number(length.value), payload = bytes.slice(offset, end);
      offset = end, pushMap(decoded.messages, field, payload);
      const text = new TextDecoder().decode(payload);
      /^[\x09\x0a\x0d\x20-\x7e]*$/.test(text) && pushMap(decoded.strings, field, text);
      try {
        pushMapValues(decoded.packedVarints, field, readPackedVarints(payload));
      } catch {
      }
      if (payload.length % 8 === 0)
        try {
          pushMapValues(decoded.packedDoubles, field, readPackedDoubles(payload));
        } catch {
        }
    } else if (wire === 5)
      offset += 4;
    else
      throw new Error(`Unsupported protobuf wire type ${wire}.`);
  }
  return decoded;
}
function pushMap(map, key, value) {
  const existing = map.get(key);
  existing ? existing.push(value) : map.set(key, [value]);
}
function pushMapValues(map, key, values) {
  const existing = map.get(key);
  existing ? existing.push(...values) : map.set(key, [...values]);
}
function readPackedVarints(bytes) {
  const values = [];
  let offset = 0;
  for (; offset < bytes.length; ) {
    const value = readVarint(bytes, offset);
    values.push(value.value), offset = value.offset;
  }
  return values;
}
function readPackedDoubles(bytes) {
  const values = [], view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let offset = 0; offset < bytes.length; offset += 8)
    values.push(view.getFloat64(offset, !0));
  return values;
}
function readVarint(bytes, start) {
  let value = 0n, shift = 0n, offset = start;
  for (; offset < bytes.length; ) {
    const byte = bytes[offset++];
    if (value |= BigInt(byte & 127) << shift, (byte & 128) === 0) return { value, offset };
    shift += 7n;
  }
  throw new Error("Unexpected end of varint.");
}
function message(fields) {
  return concat(fields.filter((field) => field.length > 0));
}
function empty() {
  return new Uint8Array();
}
function fieldVarint(field, value) {
  return concat([writeVarint(BigInt(field << 3)), writeVarint(BigInt(value))]);
}
function fieldBool(field, value) {
  return fieldVarint(field, value ? 1 : 0);
}
function fieldDouble(field, value) {
  const bytes = new Uint8Array(8);
  return new DataView(bytes.buffer).setFloat64(0, value, !0), concat([writeVarint(BigInt(field << 3 | 1)), bytes]);
}
function fieldString(field, value) {
  return fieldLengthDelimited(field, new TextEncoder().encode(value));
}
function fieldMessage(field, value) {
  return fieldLengthDelimited(field, value);
}
function fieldMessageIfPresent(field, value) {
  return value && value.length > 0 ? fieldMessage(field, value) : empty();
}
function optionalVarintField(field, value) {
  return value === void 0 ? empty() : fieldVarint(field, value);
}
function optionalBoolField(field, value) {
  return value === void 0 ? empty() : fieldBool(field, value);
}
function optionalDoubleField(field, value) {
  return value === void 0 ? empty() : fieldDouble(field, value);
}
function optionalStringField(field, value) {
  return value === void 0 ? empty() : fieldString(field, value);
}
function fieldPackedVarints(field, values) {
  return fieldLengthDelimited(field, concat(values.map((value) => writeVarint(BigInt(value)))));
}
function fieldPackedVarintsIfPresent(field, values) {
  return values === void 0 ? empty() : fieldPackedVarints(field, values);
}
function fieldPackedBools(field, values) {
  return fieldPackedVarints(field, values.map((value) => value ? 1 : 0));
}
function fieldPackedDoubles(field, values) {
  const bytes = new Uint8Array(values.length * 8), view = new DataView(bytes.buffer);
  return values.forEach((value, index) => view.setFloat64(index * 8, value, !0)), fieldLengthDelimited(field, bytes);
}
function fieldLengthDelimited(field, payload) {
  return concat([
    writeVarint(BigInt(field << 3 | 2)),
    writeVarint(BigInt(payload.length)),
    payload
  ]);
}
function fieldDurationSeconds(field, seconds) {
  if (seconds === void 0) return empty();
  const wholeSeconds = Math.trunc(seconds), nanos = Math.round((seconds - wholeSeconds) * 1e9);
  return fieldMessage(field, message([
    fieldVarint(1, wholeSeconds),
    nanos === 0 ? empty() : fieldVarint(2, nanos)
  ]));
}
function enumField(field, value, enumObject) {
  return value === void 0 ? empty() : fieldVarint(field, enumValue(value, enumObject));
}
function enumValue(value, enumObject) {
  if (typeof value == "number") return value;
  const resolved = enumObject[value];
  if (typeof resolved != "number")
    throw new Error(`Unknown enum value: ${String(value)}`);
  return resolved;
}
function mapFields(field, values, encodeValue) {
  return values ? Object.entries(values).map(([key, value]) => fieldMessage(field, message([
    fieldString(1, key),
    encodeValue(2, value)
  ]))) : [];
}
function solveParametersBytes(value) {
  return value instanceof Uint8Array ? value : typeof value.toProtoBytes == "function" ? value.toProtoBytes() : new MathOptSolveParameters(value).toProtoBytes();
}
function modelParametersBytes(value) {
  return value ? value instanceof Uint8Array ? value : typeof value.toProtoBytes == "function" ? value.toProtoBytes() : new MathOptModelSolveParameters(value).toProtoBytes() : null;
}
function solveMessageCallback(options) {
  return options.messageCallback ?? options.message_callback ?? options.msgCb ?? options.msg_cb;
}
function solveInterrupterState(options) {
  const interrupter = options.interrupter ?? options.solveInterrupter ?? options.solve_interrupter;
  return interrupter ? { useInterrupter: !0, interrupted: typeof interrupter.isInterrupted == "function" ? interrupter.isInterrupted() : typeof interrupter.is_interrupted == "function" ? interrupter.is_interrupted() : interrupter.interrupted === !0 } : { useInterrupter: !1, interrupted: !1 };
}
function solutionHintBytes(value) {
  return value instanceof Uint8Array ? value : typeof value.toProtoBytes == "function" ? value.toProtoBytes() : new MathOptSolutionHint(value).toProtoBytes();
}
function modelFilterBytes(value) {
  return value ? typeof value.toProtoBytes == "function" ? value.toProtoBytes() : encodeSparseVectorFilter(normalizeSparseVectorFilter(value)) : null;
}
function normalizeSparseVectorFilter(value) {
  return Array.isArray(value) ? { elements: value, filterByIds: !0 } : value;
}
function encodeSparseVectorFilter(options) {
  const explicitIds = options.ids ?? options.filteredIds ?? options.filtered_ids, elementIds = options.elements?.map((element) => {
    if (typeof element == "number" || typeof element == "bigint") return element;
    const id = element.id;
    if (id === void 0) throw new Error("MathOpt sparse filter elements must expose an id.");
    return id;
  }), ids = explicitIds ?? elementIds ?? [];
  return message([
    optionalBoolField(1, options.skipZeroValues ?? options.skip_zero_values),
    optionalBoolField(2, options.filterByIds ?? options.filter_by_ids ?? (ids.length > 0 ? !0 : void 0)),
    ids.length === 0 ? empty() : fieldPackedVarints(3, ids)
  ]);
}
function backendParametersBytes(value, ctor) {
  return value === void 0 ? null : value instanceof Uint8Array ? value : typeof value.toProtoBytes == "function" ? value.toProtoBytes() : new ctor(value).toProtoBytes();
}
function encodePdlpTerminationCriteria(criteria) {
  if (!criteria) return null;
  const simple = criteria.simpleOptimalityCriteria ?? criteria.simple_optimality_criteria, encoded = message([
    enumField(1, criteria.optimalityNorm ?? criteria.optimality_norm, PdlpOptimalityNorm),
    optionalDoubleField(4, criteria.epsPrimalInfeasible ?? criteria.eps_primal_infeasible),
    optionalDoubleField(5, criteria.epsDualInfeasible ?? criteria.eps_dual_infeasible),
    optionalDoubleField(6, criteria.timeSecLimit ?? criteria.time_sec_limit),
    optionalVarintField(7, criteria.iterationLimit ?? criteria.iteration_limit),
    optionalDoubleField(8, criteria.kktMatrixPassLimit ?? criteria.kkt_matrix_pass_limit),
    simple ? fieldMessage(9, message([
      optionalDoubleField(1, simple.epsOptimalAbsolute ?? simple.eps_optimal_absolute),
      optionalDoubleField(2, simple.epsOptimalRelative ?? simple.eps_optimal_relative)
    ])) : empty()
  ]);
  return encoded.length > 0 ? encoded : null;
}
function encodeSatParameters(parameters) {
  if (parameters === void 0) return null;
  if (parameters instanceof Uint8Array) return parameters;
  const params = parameters;
  return message([
    optionalVarintField(31, params.randomSeed ?? params.random_seed),
    optionalDoubleField(36, params.maxTimeInSeconds ?? params.max_time_in_seconds),
    optionalBoolField(41, params.logSearchProgress ?? params.log_search_progress),
    optionalBoolField(186, params.logToStdout ?? params.log_to_stdout),
    optionalBoolField(187, params.logToResponse ?? params.log_to_response),
    optionalVarintField(206, params.numWorkers ?? params.num_workers)
  ]);
}
function writeVarint(value) {
  const bytes = [];
  let current = value;
  do {
    let byte = Number(current & 0x7fn);
    current >>= 7n, current !== 0n && (byte |= 128), bytes.push(byte);
  } while (current !== 0n);
  return new Uint8Array(bytes);
}
function concat(parts) {
  const length = parts.reduce((sum, part) => sum + part.length, 0), output = new Uint8Array(length);
  let offset = 0;
  for (const part of parts)
    output.set(part, offset), offset += part.length;
  return output;
}
export {
  GScipEmphasis,
  GScipMetaParamValue,
  GScipParameters,
  GlopParameters,
  GlpkParameters,
  MathOpt,
  MathOptBoundedExpression,
  MathOptEmphasis,
  MathOptIncrementalSolver,
  MathOptIndicatorConstraint,
  MathOptLPAlgorithm,
  MathOptLinearConstraint,
  MathOptLinearExpression,
  MathOptLowerBoundedExpression,
  MathOptModel,
  MathOptModelSolveParameters,
  MathOptObjective,
  MathOptQuadraticExpression,
  MathOptQuadraticTermKey,
  MathOptSolutionHint,
  MathOptSolveInterrupter,
  MathOptSolveParameters,
  MathOptSolverType,
  MathOptSparseVectorFilter,
  MathOptUpperBoundedExpression,
  MathOptVarEqVar,
  MathOptVariable,
  PdlpLinesearchRule,
  PdlpOptimalityNorm,
  PdlpParameters,
  PdlpRestartStrategy,
  PdlpSchedulerType,
  asFlatLinearExpression,
  asFlatQuadraticExpression,
  boundedExpression,
  completeLowerBound,
  completeUpperBound,
  eq,
  evaluateExpression,
  fastSum,
  ge,
  initMathOpt,
  le,
  linearExpression,
  linearTerm,
  lowerBoundedExpression,
  multiplyLinearExpressions,
  ne,
  quadraticExpression,
  quadraticTerm,
  upperBoundedExpression,
  variableEq,
  variableNe
};
