var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);
import { loadMPSolverRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeAvailable as isGenericWorkerBridgeAvailable,
  isWorkerBridgeEnabled as isGenericWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled as setGenericWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
import * as protobufModule from "protobufjs";
let mpSolverModulePromise = null, mpSolverModule = null, mpSolverExports = null;
function isMPSolverWorkerBridgeRuntimeAvailable() {
  return isGenericWorkerBridgeAvailable();
}
function shouldUseMPSolverBridge() {
  return isMPSolverWorkerBridgeRuntimeAvailable() && shouldUseWorkerBridge();
}
function toNumber(value) {
  return typeof value == "bigint" ? Number(value) : value;
}
function stringBytes(value) {
  return new TextEncoder().encode(`${value}\0`);
}
function wrap(module, name, returnType, argTypes) {
  return module.cwrap(name, returnType, argTypes);
}
function createMpSolverExports(module) {
  return {
    solverInfinity: wrap(module, "mp_solver_infinity", "number", []),
    solverSupportsProblemType: wrap(module, "mp_solver_supports_problem_type", "number", ["number"]),
    solverCreate: wrap(module, "mp_solver_create", "number", ["number", "number"]),
    solverCreateSolver: wrap(module, "mp_solver_create_solver", "number", ["number"]),
    solverParseSolverType: wrap(module, "mp_solver_parse_solver_type", "number", ["number"]),
    solverName: wrap(module, "mp_solver_name", "number", ["number"]),
    solverProblemType: wrap(module, "mp_solver_problem_type", "number", ["number"]),
    solverIsMip: wrap(module, "mp_solver_is_mip", "number", ["number"]),
    solverClear: wrap(module, "mp_solver_clear", void 0, ["number"]),
    solverDelete: wrap(module, "mp_solver_delete", void 0, ["number"]),
    solverVariable: wrap(module, "mp_solver_variable", "number", ["number", "number"]),
    solverLookupVariable: wrap(module, "mp_solver_lookup_variable", "number", ["number", "number"]),
    solverVar: wrap(module, "mp_solver_var", "number", ["number", "number", "number", "number", "number"]),
    solverNumVar: wrap(module, "mp_solver_num_var", "number", ["number", "number", "number", "number"]),
    solverIntVar: wrap(module, "mp_solver_int_var", "number", ["number", "number", "number", "number"]),
    solverBoolVar: wrap(module, "mp_solver_bool_var", "number", ["number", "number"]),
    solverConstraint: wrap(module, "mp_solver_constraint", "number", ["number", "number"]),
    solverLookupConstraint: wrap(module, "mp_solver_lookup_constraint", "number", ["number", "number"]),
    solverRowConstraint: wrap(module, "mp_solver_row_constraint", "number", ["number", "number", "number", "number"]),
    solverUnboundedRowConstraint: wrap(module, "mp_solver_unbounded_row_constraint", "number", ["number", "number"]),
    constraintClear: wrap(module, "mp_constraint_clear", void 0, ["number"]),
    constraintSetCoefficient: wrap(module, "mp_constraint_set_coefficient", void 0, ["number", "number", "number"]),
    constraintGetCoefficient: wrap(module, "mp_constraint_get_coefficient", "number", ["number", "number"]),
    constraintName: wrap(module, "mp_constraint_name", "number", ["number"]),
    constraintIndex: wrap(module, "mp_constraint_index", "number", ["number"]),
    constraintLb: wrap(module, "mp_constraint_lb", "number", ["number"]),
    constraintUb: wrap(module, "mp_constraint_ub", "number", ["number"]),
    constraintSetLb: wrap(module, "mp_constraint_set_lb", void 0, ["number", "number"]),
    constraintSetUb: wrap(module, "mp_constraint_set_ub", void 0, ["number", "number"]),
    constraintSetBounds: wrap(module, "mp_constraint_set_bounds", void 0, ["number", "number", "number"]),
    constraintDualValue: wrap(module, "mp_constraint_dual_value", "number", ["number"]),
    constraintBasisStatus: wrap(module, "mp_constraint_basis_status", "number", ["number"]),
    constraintIsLazy: wrap(module, "mp_constraint_is_lazy", "number", ["number"]),
    constraintSetIsLazy: wrap(module, "mp_constraint_set_is_lazy", void 0, ["number", "number"]),
    objectiveClear: wrap(module, "mp_objective_clear", void 0, ["number"]),
    objectiveSetCoefficient: wrap(module, "mp_objective_set_coefficient", void 0, ["number", "number", "number"]),
    objectiveGetCoefficient: wrap(module, "mp_objective_get_coefficient", "number", ["number", "number"]),
    objectiveSetOffset: wrap(module, "mp_objective_set_offset", void 0, ["number", "number"]),
    objectiveOffset: wrap(module, "mp_objective_offset", "number", ["number"]),
    objectiveAddOffset: wrap(module, "mp_objective_add_offset", void 0, ["number", "number"]),
    objectiveSetOptimizationDirection: wrap(module, "mp_objective_set_optimization_direction", void 0, ["number", "number"]),
    objectiveSetMinimization: wrap(module, "mp_objective_set_minimization", void 0, ["number"]),
    objectiveSetMaximization: wrap(module, "mp_objective_set_maximization", void 0, ["number"]),
    objectiveValue: wrap(module, "mp_objective_value", "number", ["number"]),
    objectiveBestBound: wrap(module, "mp_objective_best_bound", "number", ["number"]),
    objectiveMaximization: wrap(module, "mp_objective_maximization", "number", ["number"]),
    objectiveMinimization: wrap(module, "mp_objective_minimization", "number", ["number"]),
    solverExportModelProto: wrap(module, "mp_solver_export_model_proto", "number", ["number", "number"]),
    solverExportModelRequestProto: wrap(module, "mp_solver_export_model_request_proto", "number", ["number", "number", "number", "number", "number", "number"]),
    solverLoadSolutionProto: wrap(module, "mp_solver_load_solution_proto", "number", ["number", "number", "number", "number"]),
    solverVerifySolution: wrap(module, "mp_solver_verify_solution", "number", ["number", "number", "number"]),
    solverReset: wrap(module, "mp_solver_reset", void 0, ["number"]),
    solverInterruptSolve: wrap(module, "mp_solver_interrupt_solve", "number", ["number"]),
    solverNextSolution: wrap(module, "mp_solver_next_solution", "number", ["number"]),
    solverEnableOutput: wrap(module, "mp_solver_enable_output", void 0, ["number"]),
    solverSuppressOutput: wrap(module, "mp_solver_suppress_output", void 0, ["number"]),
    solverOutputIsEnabled: wrap(module, "mp_solver_output_is_enabled", "number", ["number"]),
    solverSetTimeLimit: wrap(module, "mp_solver_set_time_limit", void 0, ["number", "bigint"]),
    solverTimeLimit: wrap(module, "mp_solver_time_limit", "bigint", ["number"]),
    solverSetNumThreads: wrap(module, "mp_solver_set_num_threads", "number", ["number", "number"]),
    solverGetNumThreads: wrap(module, "mp_solver_get_num_threads", "number", ["number"]),
    solverSetSolverSpecificParametersAsString: wrap(module, "mp_solver_set_solver_specific_parameters_as_string", "number", ["number", "number"]),
    solverGetSolverSpecificParametersAsString: wrap(module, "mp_solver_get_solver_specific_parameters_as_string", "number", ["number"]),
    solverSolverVersion: wrap(module, "mp_solver_solver_version", "number", ["number"]),
    solverExportModelAsLpFormat: wrap(module, "mp_solver_export_model_as_lp_format", "number", ["number", "number"]),
    solverExportModelAsMpsFormat: wrap(module, "mp_solver_export_model_as_mps_format", "number", ["number", "number", "number"]),
    solverConstraintActivity: wrap(module, "mp_solver_constraint_activity", "number", ["number", "number"]),
    solverComputeExactConditionNumber: wrap(module, "mp_solver_compute_exact_condition_number", "number", ["number"]),
    solverSetHint: wrap(module, "mp_solver_set_hint", void 0, ["number", "number", "number", "number"]),
    lastStringResult: wrap(module, "mp_last_string_result", "number", []),
    solverNumVariables: wrap(module, "mp_solver_num_variables", "number", ["number"]),
    solverNumConstraints: wrap(module, "mp_solver_num_constraints", "number", ["number"]),
    solverWallTime: wrap(module, "mp_solver_wall_time", "bigint", ["number"]),
    solverIterations: wrap(module, "mp_solver_iterations", "bigint", ["number"]),
    solverNodes: wrap(module, "mp_solver_nodes", "bigint", ["number"]),
    variableName: wrap(module, "mp_variable_name", "number", ["number"]),
    variableIndex: wrap(module, "mp_variable_index", "number", ["number"]),
    variableSolutionValue: wrap(module, "mp_variable_solution_value", "number", ["number"]),
    variableUnroundedSolutionValue: wrap(module, "mp_variable_unrounded_solution_value", "number", ["number"]),
    variableReducedCost: wrap(module, "mp_variable_reduced_cost", "number", ["number"]),
    variableBasisStatus: wrap(module, "mp_variable_basis_status", "number", ["number"]),
    variableLb: wrap(module, "mp_variable_lb", "number", ["number"]),
    variableUb: wrap(module, "mp_variable_ub", "number", ["number"]),
    variableInteger: wrap(module, "mp_variable_integer", "number", ["number"]),
    variableSetInteger: wrap(module, "mp_variable_set_integer", void 0, ["number", "number"]),
    variableSetLb: wrap(module, "mp_variable_set_lb", void 0, ["number", "number"]),
    variableSetUb: wrap(module, "mp_variable_set_ub", void 0, ["number", "number"]),
    variableSetBounds: wrap(module, "mp_variable_set_bounds", void 0, ["number", "number", "number"]),
    variableBranchingPriority: wrap(module, "mp_variable_branching_priority", "number", ["number"]),
    variableSetBranchingPriority: wrap(module, "mp_variable_set_branching_priority", void 0, ["number", "number"]),
    parametersCreate: wrap(module, "mp_solver_parameters_create", "number", []),
    parametersDelete: wrap(module, "mp_solver_parameters_delete", void 0, ["number"]),
    parametersSetDoubleParam: wrap(module, "mp_solver_parameters_set_double_param", void 0, ["number", "number", "number"]),
    parametersGetDoubleParam: wrap(module, "mp_solver_parameters_get_double_param", "number", ["number", "number"]),
    parametersResetDoubleParam: wrap(module, "mp_solver_parameters_reset_double_param", void 0, ["number", "number"]),
    parametersSetIntegerParam: wrap(module, "mp_solver_parameters_set_integer_param", void 0, ["number", "number", "number"]),
    parametersGetIntegerParam: wrap(module, "mp_solver_parameters_get_integer_param", "number", ["number", "number"]),
    parametersResetIntegerParam: wrap(module, "mp_solver_parameters_reset_integer_param", void 0, ["number", "number"]),
    parametersReset: wrap(module, "mp_solver_parameters_reset", void 0, ["number"])
  };
}
async function loadMpSolverModule() {
  return mpSolverModulePromise ?? (mpSolverModulePromise = loadMPSolverRuntime()), mpSolverModule = await mpSolverModulePromise, mpSolverExports ?? (mpSolverExports = createMpSolverExports(mpSolverModule)), mpSolverModule;
}
function getMpSolverModule() {
  if (!mpSolverModule)
    throw new Error("MPSolver API is not initialized. Call await initMPSolver() before constructing MPSolver objects.");
  return mpSolverModule;
}
function getMpSolverExports() {
  if (!mpSolverExports)
    throw new Error("MPSolver API is not initialized. Call await initMPSolver() before constructing MPSolver objects.");
  return mpSolverExports;
}
function withCString(module, value, fn) {
  const bytes = stringBytes(value), ptr = module._malloc(bytes.byteLength);
  module.HEAPU8.set(bytes, ptr);
  try {
    return fn(ptr);
  } finally {
    module._free(ptr);
  }
}
async function withCStringAsync(module, value, fn) {
  const bytes = stringBytes(value), ptr = module._malloc(bytes.byteLength);
  module.HEAPU8.set(bytes, ptr);
  try {
    return await fn(ptr);
  } finally {
    module._free(ptr);
  }
}
function readUint32LE(buffer, ptr) {
  return new DataView(buffer, ptr, 4).getUint32(0, !0);
}
function copyBytesToHeap(module, bytes) {
  if (!bytes?.length) return 0;
  const ptr = module._malloc(bytes.length);
  return module.HEAPU8.set(bytes, ptr), ptr;
}
async function readNativeBytes(module, fn) {
  const lenPtr = module._malloc(4);
  let responsePtr = 0;
  try {
    responsePtr = await fn(lenPtr);
    const len = readUint32LE(module.HEAPU8.buffer, lenPtr);
    return responsePtr && len ? module.HEAPU8.slice(responsePtr, responsePtr + len) : new Uint8Array();
  } finally {
    responsePtr && module.ccall("free_buffer", void 0, ["number"], [responsePtr]), module._free(lenPtr);
  }
}
let linearSolverSchemasPromise = null, linearSolverRootPromise = null, mpModelTypePromise = null, mpModelRequestTypePromise = null, mpSolutionResponseTypePromise = null;
async function getLinearSolverSchemas() {
  return linearSolverSchemasPromise ?? (linearSolverSchemasPromise = (async () => {
    if (shouldUseMPSolverBridge()) {
      const response = await postWorkerRequest({
        type: "getSchemas",
        id: nextWorkerBridgeRequestId(),
        schema: "mp_solver"
      });
      if (response.schema !== "mp_solver")
        throw new Error("Worker returned the wrong schema payload for MPSolver.");
      return {
        linear_solver: response.schemas.linear_solver,
        optional_boolean: response.schemas.optional_boolean
      };
    }
    const module = await loadMpSolverModule();
    return {
      linear_solver: module.ccall("get_linear_solver_schema", "string", [], []),
      optional_boolean: module.ccall("get_optional_boolean_schema", "string", [], [])
    };
  })()), linearSolverSchemasPromise;
}
async function resolveLinearSolverRoot() {
  return linearSolverRootPromise ?? (linearSolverRootPromise = (async () => {
    const schemas = await getLinearSolverSchemas(), optionalRoot = protobufModule.parse(schemas.optional_boolean).root, linearSolverSource = schemas.linear_solver.replace(/^import "ortools\/util\/optional_boolean\.proto";\s*$/m, "");
    return protobufModule.parse(linearSolverSource, optionalRoot).root;
  })()), linearSolverRootPromise;
}
async function resolveMPModelRequestType() {
  return mpModelRequestTypePromise ?? (mpModelRequestTypePromise = (async () => (await resolveLinearSolverRoot()).lookupType("operations_research.MPModelRequest"))()), mpModelRequestTypePromise;
}
async function resolveMPModelType() {
  return mpModelTypePromise ?? (mpModelTypePromise = (async () => (await resolveLinearSolverRoot()).lookupType("operations_research.MPModelProto"))()), mpModelTypePromise;
}
async function resolveMPSolutionResponseType() {
  return mpSolutionResponseTypePromise ?? (mpSolutionResponseTypePromise = (async () => (await resolveLinearSolverRoot()).lookupType("operations_research.MPSolutionResponse"))()), mpSolutionResponseTypePromise;
}
async function encodeMPModelRequest(request) {
  const type = await resolveMPModelRequestType(), error = type.verify(request);
  if (error)
    throw new Error(`MPSolver.createModelRequest: ${error}`);
  return type.encode(type.create(request)).finish();
}
async function encodeMPModel(model) {
  const type = await resolveMPModelType(), error = type.verify(model);
  if (error)
    throw new Error(`MPSolver.exportModelProto: ${error}`);
  return type.encode(type.create(model)).finish();
}
async function decodeMPSolutionResponse(bytes) {
  const type = await resolveMPSolutionResponseType();
  return type.toObject(type.decode(bytes), {
    enums: String,
    longs: Number,
    defaults: !0,
    arrays: !0,
    objects: !0
  });
}
async function encodeMPSolutionResponse(response) {
  const type = await resolveMPSolutionResponseType(), error = type.verify(response);
  if (error)
    throw new Error(`MPSolver.createSolutionResponse: ${error}`);
  return type.encode(type.create(response)).finish();
}
function normalizedNumThreads(options = {}) {
  const numThreads = options.numThreads ?? options.num_threads;
  return typeof numThreads == "number" && Number.isInteger(numThreads) && numThreads > 1 ? numThreads : void 0;
}
async function solveModelRequestDirect(requestBytes, options = {}) {
  const module = await loadMpSolverModule(), requestPtr = copyBytesToHeap(module, requestBytes);
  try {
    const numThreads = normalizedNumThreads(options);
    return readNativeBytes(module, async (lenPtr) => numThreads !== void 0 ? await module.ccall(
      "mp_solver_solve_model_request_with_threads",
      "number",
      ["number", "number", "number", "number"],
      [requestPtr, requestBytes.length, numThreads, lenPtr],
      { async: !0 }
    ) : await module.ccall(
      "mp_solver_solve_model_request",
      "number",
      ["number", "number", "number"],
      [requestPtr, requestBytes.length, lenPtr],
      { async: !0 }
    ));
  } finally {
    requestPtr && module._free(requestPtr);
  }
}
async function solveModelRequestBytes(requestBytes, options = {}) {
  if (shouldUseMPSolverBridge()) {
    const numThreads = normalizedNumThreads(options), response = await postWorkerRequest({
      type: "mpSolverSolve",
      id: nextWorkerBridgeRequestId(),
      requestBytes,
      numThreads
    });
    return new Uint8Array(response.bytes);
  }
  return solveModelRequestDirect(requestBytes, options);
}
function readCString(module, ptr) {
  return ptr === 0 ? "" : module.UTF8ToString(ptr);
}
async function initMPSolver() {
  shouldUseMPSolverBridge() || await loadMpSolverModule();
}
async function initKnapsack() {
  shouldUseMPSolverBridge() || await loadMpSolverModule();
}
function isMPSolverWorkerBridgeAvailable() {
  return isMPSolverWorkerBridgeRuntimeAvailable();
}
function setMPSolverWorkerBridgeEnabled(enabled) {
  setGenericWorkerBridgeEnabled(enabled);
}
function isMPSolverWorkerBridgeEnabled() {
  return isGenericWorkerBridgeEnabled() && isMPSolverWorkerBridgeRuntimeAvailable();
}
var OptimizationProblemType = /* @__PURE__ */ ((OptimizationProblemType2) => (OptimizationProblemType2[OptimizationProblemType2.CLP_LINEAR_PROGRAMMING = 0] = "CLP_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.GLPK_LINEAR_PROGRAMMING = 1] = "GLPK_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.GLOP_LINEAR_PROGRAMMING = 2] = "GLOP_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.PDLP_LINEAR_PROGRAMMING = 8] = "PDLP_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.HIGHS_LINEAR_PROGRAMMING = 15] = "HIGHS_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.SCIP_MIXED_INTEGER_PROGRAMMING = 3] = "SCIP_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.GLPK_MIXED_INTEGER_PROGRAMMING = 4] = "GLPK_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.CBC_MIXED_INTEGER_PROGRAMMING = 5] = "CBC_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.HIGHS_MIXED_INTEGER_PROGRAMMING = 16] = "HIGHS_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.GUROBI_LINEAR_PROGRAMMING = 6] = "GUROBI_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.GUROBI_MIXED_INTEGER_PROGRAMMING = 7] = "GUROBI_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.CPLEX_LINEAR_PROGRAMMING = 10] = "CPLEX_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.CPLEX_MIXED_INTEGER_PROGRAMMING = 11] = "CPLEX_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.XPRESS_LINEAR_PROGRAMMING = 101] = "XPRESS_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.XPRESS_MIXED_INTEGER_PROGRAMMING = 102] = "XPRESS_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.COPT_LINEAR_PROGRAMMING = 103] = "COPT_LINEAR_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.COPT_MIXED_INTEGER_PROGRAMMING = 104] = "COPT_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.BOP_INTEGER_PROGRAMMING = 12] = "BOP_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.SAT_INTEGER_PROGRAMMING = 14] = "SAT_INTEGER_PROGRAMMING", OptimizationProblemType2[OptimizationProblemType2.KNAPSACK_MIXED_INTEGER_PROGRAMMING = 13] = "KNAPSACK_MIXED_INTEGER_PROGRAMMING", OptimizationProblemType2))(OptimizationProblemType || {}), MPSolverResultStatus = /* @__PURE__ */ ((MPSolverResultStatus2) => (MPSolverResultStatus2[MPSolverResultStatus2.OPTIMAL = 0] = "OPTIMAL", MPSolverResultStatus2[MPSolverResultStatus2.FEASIBLE = 1] = "FEASIBLE", MPSolverResultStatus2[MPSolverResultStatus2.INFEASIBLE = 2] = "INFEASIBLE", MPSolverResultStatus2[MPSolverResultStatus2.UNBOUNDED = 3] = "UNBOUNDED", MPSolverResultStatus2[MPSolverResultStatus2.ABNORMAL = 4] = "ABNORMAL", MPSolverResultStatus2[MPSolverResultStatus2.MODEL_INVALID = 5] = "MODEL_INVALID", MPSolverResultStatus2[MPSolverResultStatus2.NOT_SOLVED = 6] = "NOT_SOLVED", MPSolverResultStatus2))(MPSolverResultStatus || {}), BasisStatus = /* @__PURE__ */ ((BasisStatus2) => (BasisStatus2[BasisStatus2.FREE = 0] = "FREE", BasisStatus2[BasisStatus2.AT_LOWER_BOUND = 1] = "AT_LOWER_BOUND", BasisStatus2[BasisStatus2.AT_UPPER_BOUND = 2] = "AT_UPPER_BOUND", BasisStatus2[BasisStatus2.FIXED_VALUE = 3] = "FIXED_VALUE", BasisStatus2[BasisStatus2.BASIC = 4] = "BASIC", BasisStatus2))(BasisStatus || {}), DoubleParam = /* @__PURE__ */ ((DoubleParam2) => (DoubleParam2[DoubleParam2.RELATIVE_MIP_GAP = 0] = "RELATIVE_MIP_GAP", DoubleParam2[DoubleParam2.PRIMAL_TOLERANCE = 1] = "PRIMAL_TOLERANCE", DoubleParam2[DoubleParam2.DUAL_TOLERANCE = 2] = "DUAL_TOLERANCE", DoubleParam2))(DoubleParam || {}), IntegerParam = /* @__PURE__ */ ((IntegerParam2) => (IntegerParam2[IntegerParam2.PRESOLVE = 1e3] = "PRESOLVE", IntegerParam2[IntegerParam2.LP_ALGORITHM = 1001] = "LP_ALGORITHM", IntegerParam2[IntegerParam2.INCREMENTALITY = 1002] = "INCREMENTALITY", IntegerParam2[IntegerParam2.SCALING = 1003] = "SCALING", IntegerParam2))(IntegerParam || {}), PresolveValues = /* @__PURE__ */ ((PresolveValues2) => (PresolveValues2[PresolveValues2.PRESOLVE_OFF = 0] = "PRESOLVE_OFF", PresolveValues2[PresolveValues2.PRESOLVE_ON = 1] = "PRESOLVE_ON", PresolveValues2))(PresolveValues || {}), LpAlgorithmValues = /* @__PURE__ */ ((LpAlgorithmValues2) => (LpAlgorithmValues2[LpAlgorithmValues2.DUAL = 10] = "DUAL", LpAlgorithmValues2[LpAlgorithmValues2.PRIMAL = 11] = "PRIMAL", LpAlgorithmValues2[LpAlgorithmValues2.BARRIER = 12] = "BARRIER", LpAlgorithmValues2))(LpAlgorithmValues || {}), IncrementalityValues = /* @__PURE__ */ ((IncrementalityValues2) => (IncrementalityValues2[IncrementalityValues2.INCREMENTALITY_OFF = 0] = "INCREMENTALITY_OFF", IncrementalityValues2[IncrementalityValues2.INCREMENTALITY_ON = 1] = "INCREMENTALITY_ON", IncrementalityValues2))(IncrementalityValues || {}), ScalingValues = /* @__PURE__ */ ((ScalingValues2) => (ScalingValues2[ScalingValues2.SCALING_OFF = 0] = "SCALING_OFF", ScalingValues2[ScalingValues2.SCALING_ON = 1] = "SCALING_ON", ScalingValues2))(ScalingValues || {}), KnapsackSolverType = /* @__PURE__ */ ((KnapsackSolverType2) => (KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_BRUTE_FORCE_SOLVER = 0] = "KNAPSACK_BRUTE_FORCE_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_64ITEMS_SOLVER = 1] = "KNAPSACK_64ITEMS_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER = 2] = "KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER = 3] = "KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER = 5] = "KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER = 6] = "KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER = 7] = "KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER = 8] = "KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_DIVIDE_AND_CONQUER_SOLVER = 9] = "KNAPSACK_DIVIDE_AND_CONQUER_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER = 10] = "KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER", KnapsackSolverType2))(KnapsackSolverType || {});
function copyFloat64ToHeap(module, values) {
  if (!values.length) return 0;
  const ptr = module._malloc(values.length * Float64Array.BYTES_PER_ELEMENT);
  return new Float64Array(module.HEAPU8.buffer, ptr, values.length).set(values), ptr;
}
function flattenKnapsackWeights(weights, itemCount) {
  const flattened = [];
  for (const dimension of weights) {
    if (dimension.length !== itemCount)
      throw new Error("KnapsackSolver.init: each weight dimension must match profits length.");
    flattened.push(...dimension);
  }
  return flattened;
}
function parseKnapsackResult(serialized) {
  const result = JSON.parse(serialized);
  if (!result.ok)
    throw new Error(result.error || "KnapsackSolver.solve: native solve failed.");
  return result;
}
async function solveKnapsackDirect(solverType, name, useReduction, timeLimitSeconds, profits, weights, capacities) {
  const module = await loadMpSolverModule(), flattenedWeights = flattenKnapsackWeights(weights, profits.length), profitsPtr = copyFloat64ToHeap(module, profits), weightsPtr = copyFloat64ToHeap(module, flattenedWeights), capacitiesPtr = copyFloat64ToHeap(module, capacities);
  try {
    return await withCStringAsync(module, name, async (namePtr) => {
      const resultPtr = await module.ccall(
        "knapsack_solve_serialized",
        "number",
        ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
        [
          solverType,
          namePtr,
          useReduction ? 1 : 0,
          timeLimitSeconds,
          profitsPtr,
          profits.length,
          weightsPtr,
          weights.length,
          capacitiesPtr
        ],
        { async: !0 }
      );
      return parseKnapsackResult(readCString(module, resultPtr));
    });
  } finally {
    profitsPtr && module._free(profitsPtr), weightsPtr && module._free(weightsPtr), capacitiesPtr && module._free(capacitiesPtr);
  }
}
async function solveKnapsack(solverType, name, useReduction, timeLimitSeconds, profits, weights, capacities) {
  if (shouldUseMPSolverBridge()) {
    const response = await postWorkerRequest({
      type: "knapsackSolve",
      id: nextWorkerBridgeRequestId(),
      solverType,
      name,
      useReduction,
      timeLimitSeconds,
      profits,
      weights,
      capacities
    });
    return parseKnapsackResult(response.result);
  }
  return solveKnapsackDirect(solverType, name, useReduction, timeLimitSeconds, profits, weights, capacities);
}
class KnapsackSolver {
  constructor(solverType, solverName) {
    __publicField(this, "solverType", solverType);
    __publicField(this, "solverName", solverName);
    __publicField(this, "profits", []);
    __publicField(this, "weights", []);
    __publicField(this, "capacities", []);
    __publicField(this, "useReduction", !0);
    __publicField(this, "timeLimitSeconds", 0);
    __publicField(this, "solutionContains", []);
    __publicField(this, "solutionOptimal", !1);
    shouldUseMPSolverBridge() || getMpSolverModule();
  }
  init(profits, weights, capacities) {
    if (weights.length !== capacities.length)
      throw new Error("KnapsackSolver.init: weights dimensions must match capacities length.");
    flattenKnapsackWeights(weights, profits.length), this.profits = [...profits], this.weights = weights.map((dimension) => [...dimension]), this.capacities = [...capacities], this.solutionContains = [], this.solutionOptimal = !1;
  }
  Init(profits, weights, capacities) {
    this.init(profits, weights, capacities);
  }
  async solve() {
    const result = await solveKnapsack(
      this.solverType,
      this.solverName,
      this.useReduction,
      this.timeLimitSeconds,
      this.profits,
      this.weights,
      this.capacities
    );
    return this.solutionContains = result.contains ?? [], this.solutionOptimal = result.optimal === !0, Number(result.profit ?? 0);
  }
  Solve() {
    return this.solve();
  }
  best_solution_contains(itemId) {
    return this.solutionContains[itemId] === !0;
  }
  BestSolutionContains(itemId) {
    return this.best_solution_contains(itemId);
  }
  is_solution_optimal() {
    return this.solutionOptimal;
  }
  IsSolutionOptimal() {
    return this.is_solution_optimal();
  }
  set_use_reduction(useReduction) {
    this.useReduction = useReduction;
  }
  SetUseReduction(useReduction) {
    this.set_use_reduction(useReduction);
  }
  set_time_limit(timeLimitSeconds) {
    this.timeLimitSeconds = timeLimitSeconds;
  }
  SetTimeLimit(timeLimitSeconds) {
    this.set_time_limit(timeLimitSeconds);
  }
  getName() {
    return this.solverName;
  }
  GetName() {
    return this.getName();
  }
}
__publicField(KnapsackSolver, "SolverType", KnapsackSolverType), __publicField(KnapsackSolver, "KNAPSACK_BRUTE_FORCE_SOLVER", 0 /* KNAPSACK_BRUTE_FORCE_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_64ITEMS_SOLVER", 1 /* KNAPSACK_64ITEMS_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER", 2 /* KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER", 3 /* KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER", 5 /* KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER", 6 /* KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER", 7 /* KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER", 8 /* KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_DIVIDE_AND_CONQUER_SOLVER", 9 /* KNAPSACK_DIVIDE_AND_CONQUER_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER", 10 /* KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER */);
const workerSupportedProblemTypes = /* @__PURE__ */ new Set([
  0 /* CLP_LINEAR_PROGRAMMING */,
  1 /* GLPK_LINEAR_PROGRAMMING */,
  2 /* GLOP_LINEAR_PROGRAMMING */,
  3 /* SCIP_MIXED_INTEGER_PROGRAMMING */,
  4 /* GLPK_MIXED_INTEGER_PROGRAMMING */,
  5 /* CBC_MIXED_INTEGER_PROGRAMMING */,
  12 /* BOP_INTEGER_PROGRAMMING */,
  14 /* SAT_INTEGER_PROGRAMMING */,
  13 /* KNAPSACK_MIXED_INTEGER_PROGRAMMING */
]), workerSolverTypeAliases = /* @__PURE__ */ new Map([
  ["CLP", 0 /* CLP_LINEAR_PROGRAMMING */],
  ["CLP_LINEAR_PROGRAMMING", 0 /* CLP_LINEAR_PROGRAMMING */],
  ["GLPK_LP", 1 /* GLPK_LINEAR_PROGRAMMING */],
  ["GLPK_LINEAR_PROGRAMMING", 1 /* GLPK_LINEAR_PROGRAMMING */],
  ["GLOP", 2 /* GLOP_LINEAR_PROGRAMMING */],
  ["GLOP_LINEAR_PROGRAMMING", 2 /* GLOP_LINEAR_PROGRAMMING */],
  ["SCIP", 3 /* SCIP_MIXED_INTEGER_PROGRAMMING */],
  ["SCIP_MIXED_INTEGER_PROGRAMMING", 3 /* SCIP_MIXED_INTEGER_PROGRAMMING */],
  ["CBC", 5 /* CBC_MIXED_INTEGER_PROGRAMMING */],
  ["CBC_MIXED_INTEGER_PROGRAMMING", 5 /* CBC_MIXED_INTEGER_PROGRAMMING */],
  ["GLPK", 4 /* GLPK_MIXED_INTEGER_PROGRAMMING */],
  ["GLPK_MIP", 4 /* GLPK_MIXED_INTEGER_PROGRAMMING */],
  ["GLPK_MIXED_INTEGER_PROGRAMMING", 4 /* GLPK_MIXED_INTEGER_PROGRAMMING */],
  ["BOP", 12 /* BOP_INTEGER_PROGRAMMING */],
  ["BOP_INTEGER_PROGRAMMING", 12 /* BOP_INTEGER_PROGRAMMING */],
  ["SAT", 14 /* SAT_INTEGER_PROGRAMMING */],
  ["CP_SAT", 14 /* SAT_INTEGER_PROGRAMMING */],
  ["SAT_INTEGER_PROGRAMMING", 14 /* SAT_INTEGER_PROGRAMMING */],
  ["KNAPSACK", 13 /* KNAPSACK_MIXED_INTEGER_PROGRAMMING */],
  ["KNAPSACK_MIXED_INTEGER_PROGRAMMING", 13 /* KNAPSACK_MIXED_INTEGER_PROGRAMMING */]
]);
function normalizeWorkerSolverId(solverId) {
  return solverId.trim().toUpperCase().replace(/[\s-]+/g, "_");
}
function workerParseSolverType(solverId) {
  return workerSolverTypeAliases.get(normalizeWorkerSolverId(solverId)) ?? null;
}
function workerSupportsProblemType(problemType) {
  return workerSupportedProblemTypes.has(problemType);
}
function workerProblemIsMip(problemType) {
  return problemType === 3 /* SCIP_MIXED_INTEGER_PROGRAMMING */ || problemType === 4 /* GLPK_MIXED_INTEGER_PROGRAMMING */ || problemType === 5 /* CBC_MIXED_INTEGER_PROGRAMMING */ || problemType === 16 /* HIGHS_MIXED_INTEGER_PROGRAMMING */ || problemType === 7 /* GUROBI_MIXED_INTEGER_PROGRAMMING */ || problemType === 11 /* CPLEX_MIXED_INTEGER_PROGRAMMING */ || problemType === 102 /* XPRESS_MIXED_INTEGER_PROGRAMMING */ || problemType === 104 /* COPT_MIXED_INTEGER_PROGRAMMING */ || problemType === 12 /* BOP_INTEGER_PROGRAMMING */ || problemType === 14 /* SAT_INTEGER_PROGRAMMING */ || problemType === 13 /* KNAPSACK_MIXED_INTEGER_PROGRAMMING */;
}
function workerProblemSupportsNumThreads(problemType) {
  return problemType === 3 /* SCIP_MIXED_INTEGER_PROGRAMMING */ || problemType === 5 /* CBC_MIXED_INTEGER_PROGRAMMING */ || problemType === 14 /* SAT_INTEGER_PROGRAMMING */;
}
function createWorkerSolverState(name, problemType) {
  if (!workerSupportsProblemType(problemType))
    throw new Error(`MPSolver: problem type ${problemType} is not supported by the worker bridge facade.`);
  return {
    name,
    problemType,
    variables: [],
    constraints: [],
    objective: {
      coeffs: /* @__PURE__ */ new Map(),
      offset: 0,
      maximize: !1,
      value: 0,
      bestBound: 0
    },
    outputEnabled: !1,
    timeLimitMs: 0,
    numThreads: 1,
    solverSpecificParameters: "",
    hints: null,
    deleted: !1,
    wallTimeMs: 0,
    iterations: 0,
    nodes: 0,
    solutionLoaded: !1
  };
}
function workerDoubleDefault(param) {
  return param === 0 /* RELATIVE_MIP_GAP */ ? MPSolverParameters.kDefaultRelativeMipGap : param === 1 /* PRIMAL_TOLERANCE */ ? MPSolverParameters.kDefaultPrimalTolerance : param === 2 /* DUAL_TOLERANCE */ ? MPSolverParameters.kDefaultDualTolerance : 0;
}
function workerIntegerDefault(param) {
  return param === 1e3 /* PRESOLVE */ ? MPSolverParameters.kDefaultPresolve : param === 1002 /* INCREMENTALITY */ ? MPSolverParameters.kDefaultIncrementality : param === 1001 /* LP_ALGORITHM */ ? 10 /* DUAL */ : param === 1003 /* SCALING */ ? 1 /* SCALING_ON */ : 0;
}
function workerStatusToResultStatus(status) {
  if (typeof status == "number") {
    if (status === 0) return 0 /* OPTIMAL */;
    if (status === 1) return 1 /* FEASIBLE */;
    if (status === 2) return 2 /* INFEASIBLE */;
    if (status === 3) return 3 /* UNBOUNDED */;
    if (status === 4) return 4 /* ABNORMAL */;
    if (status === 5) return 5 /* MODEL_INVALID */;
    if (status === 6) return 6 /* NOT_SOLVED */;
  }
  return status === "MPSOLVER_OPTIMAL" ? 0 /* OPTIMAL */ : status === "MPSOLVER_FEASIBLE" ? 1 /* FEASIBLE */ : status === "MPSOLVER_INFEASIBLE" ? 2 /* INFEASIBLE */ : status === "MPSOLVER_UNBOUNDED" ? 3 /* UNBOUNDED */ : status === "MPSOLVER_ABNORMAL" ? 4 /* ABNORMAL */ : status === "MPSOLVER_MODEL_INVALID" || status === "MPSOLVER_MODEL_INVALID_SOLUTION_HINT" || status === "MPSOLVER_MODEL_INVALID_SOLVER_PARAMETERS" ? 5 /* MODEL_INVALID */ : 6 /* NOT_SOLVED */;
}
function workerStatusHasSolution(status) {
  const resultStatus = workerStatusToResultStatus(status);
  return resultStatus === 0 /* OPTIMAL */ || resultStatus === 1 /* FEASIBLE */;
}
function workerConstraintActivity(state, constraint) {
  let value = 0;
  for (const [variableIndex, coefficient] of constraint.coeffs)
    value += coefficient * (state.variables[variableIndex]?.solutionValue ?? 0);
  return value;
}
function workerObjectiveValue(state) {
  let value = state.objective.offset;
  for (const [variableIndex, coefficient] of state.objective.coeffs)
    value += coefficient * (state.variables[variableIndex]?.solutionValue ?? 0);
  return value;
}
function workerBasisStatusForBounds(value, lb, ub) {
  return Number.isFinite(lb) && Number.isFinite(ub) && Math.abs(lb - ub) <= 1e-7 ? 3 /* FIXED_VALUE */ : Number.isFinite(lb) && Math.abs(value - lb) <= 1e-7 ? 1 /* AT_LOWER_BOUND */ : Number.isFinite(ub) && Math.abs(value - ub) <= 1e-7 ? 2 /* AT_UPPER_BOUND */ : 4 /* BASIC */;
}
function workerModelProto(state) {
  const model = {
    name: state.name,
    maximize: state.objective.maximize,
    objectiveOffset: state.objective.offset,
    variable: state.variables.map((variable) => ({
      lowerBound: variable.lb,
      upperBound: variable.ub,
      objectiveCoefficient: state.objective.coeffs.get(variable.index) ?? 0,
      isInteger: variable.integer,
      name: variable.name,
      branchingPriority: variable.branchingPriority
    })),
    constraint: state.constraints.map((constraint) => ({
      lowerBound: constraint.lb,
      upperBound: constraint.ub,
      varIndex: [...constraint.coeffs.keys()],
      coefficient: [...constraint.coeffs.values()],
      name: constraint.name,
      isLazy: constraint.lazy
    }))
  };
  return state.hints && state.hints.varIndex.length > 0 && (model.solutionHint = state.hints), model;
}
function workerModelRequest(state, options = {}) {
  const request = {
    solverType: options.solverType ?? state.problemType,
    model: workerModelProto(state)
  }, timeLimitSeconds = options.timeLimitSeconds ?? (state.timeLimitMs > 0 ? state.timeLimitMs / 1e3 : void 0);
  timeLimitSeconds !== void 0 && (request.solverTimeLimitSeconds = timeLimitSeconds), (options.enableOutput ?? state.outputEnabled) && (request.enableInternalSolverOutput = !0);
  const solverSpecificParameters = options.solverSpecificParameters ?? state.solverSpecificParameters;
  return solverSpecificParameters && (request.solverSpecificParameters = solverSpecificParameters), request;
}
function applyWorkerSolutionResponse(state, response) {
  const loaded = workerStatusHasSolution(response.status), variableValues = Array.isArray(response.variableValue) ? response.variableValue : [];
  for (const variable of state.variables) {
    const value = Number(variableValues[variable.index] ?? 0);
    variable.solutionValue = value, variable.unroundedSolutionValue = value, variable.basisStatus = workerBasisStatusForBounds(value, variable.lb, variable.ub);
  }
  const reducedCosts = Array.isArray(response.reducedCost) ? response.reducedCost : [];
  for (const variable of state.variables)
    variable.index < reducedCosts.length && (variable.reducedCost = Number(reducedCosts[variable.index]));
  const dualValues = Array.isArray(response.dualValue) ? response.dualValue : [];
  for (const constraint of state.constraints)
    constraint.index < dualValues.length && (constraint.dualValue = Number(dualValues[constraint.index])), constraint.basisStatus = workerBasisStatusForBounds(workerConstraintActivity(state, constraint), constraint.lb, constraint.ub);
  state.objective.value = typeof response.objectiveValue == "number" ? response.objectiveValue : workerObjectiveValue(state), state.objective.bestBound = workerProblemIsMip(state.problemType) && typeof response.bestObjectiveBound == "number" ? response.bestObjectiveBound : state.objective.value;
  const solveInfo = response.solveInfo;
  return typeof solveInfo?.solveWallTimeSeconds == "number" && (state.wallTimeMs = Math.round(solveInfo.solveWallTimeSeconds * 1e3)), state.solutionLoaded = loaded, loaded;
}
function resetWorkerSolution(state) {
  for (const variable of state.variables)
    variable.solutionValue = 0, variable.unroundedSolutionValue = 0, variable.reducedCost = 0, variable.basisStatus = 0 /* FREE */;
  for (const constraint of state.constraints)
    constraint.dualValue = 0, constraint.basisStatus = 0 /* FREE */;
  state.objective.value = 0, state.objective.bestBound = 0, state.wallTimeMs = 0, state.iterations = 0, state.nodes = 0, state.solutionLoaded = !1;
}
function nativeVariableHandle(ref) {
  if (!ref.handle) throw new Error("MPSolver: native variable handle is not available.");
  return ref.handle;
}
function nativeConstraintHandle(ref) {
  if (!ref.handle) throw new Error("MPSolver: native constraint handle is not available.");
  return ref.handle;
}
class NativeMPSolverParametersBackend {
  constructor(exports = getMpSolverExports()) {
    __publicField(this, "exports", exports);
    __publicField(this, "handle", 0);
    if (this.handle = this.exports.parametersCreate(), this.handle === 0)
      throw new Error("MPSolverParameters: failed to create parameters.");
  }
  nativeHandle() {
    return this.handle;
  }
  setDoubleParam(param, value) {
    this.exports.parametersSetDoubleParam(this.handle, param, value);
  }
  getDoubleParam(param) {
    return this.exports.parametersGetDoubleParam(this.handle, param);
  }
  resetDoubleParam(param) {
    this.exports.parametersResetDoubleParam(this.handle, param);
  }
  setIntegerParam(param, value) {
    this.exports.parametersSetIntegerParam(this.handle, param, value);
  }
  getIntegerParam(param) {
    return this.exports.parametersGetIntegerParam(this.handle, param);
  }
  resetIntegerParam(param) {
    this.exports.parametersResetIntegerParam(this.handle, param);
  }
  reset() {
    this.exports.parametersReset(this.handle);
  }
  delete() {
    this.handle !== 0 && (this.exports.parametersDelete(this.handle), this.handle = 0);
  }
}
class BridgeMPSolverParametersBackend {
  constructor() {
    __publicField(this, "doubleParams", /* @__PURE__ */ new Map());
    __publicField(this, "integerParams", /* @__PURE__ */ new Map());
  }
  nativeHandle() {
    throw new Error("MPSolverParameters: native handle is not available for worker-backed parameters.");
  }
  setDoubleParam(param, value) {
    this.doubleParams.set(param, value);
  }
  getDoubleParam(param) {
    return this.doubleParams.get(param) ?? workerDoubleDefault(param);
  }
  resetDoubleParam(param) {
    this.doubleParams.delete(param);
  }
  setIntegerParam(param, value) {
    this.integerParams.set(param, value);
  }
  getIntegerParam(param) {
    return this.integerParams.get(param) ?? workerIntegerDefault(param);
  }
  resetIntegerParam(param) {
    this.integerParams.delete(param);
  }
  reset() {
    this.doubleParams.clear(), this.integerParams.clear();
  }
  delete() {
    this.reset();
  }
}
class NativeMPSolverBackend {
  constructor(module, exports, nameOrHandle, problemType) {
    __publicField(this, "module", module);
    __publicField(this, "exports", exports);
    __publicField(this, "handle", 0);
    if (typeof nameOrHandle == "number" ? this.handle = nameOrHandle : this.handle = withCString(this.module, nameOrHandle, (namePtr) => this.exports.solverCreate(namePtr, problemType)), this.handle === 0)
      throw new Error("MPSolver: failed to create solver.");
  }
  static create(name, problemType) {
    return new NativeMPSolverBackend(getMpSolverModule(), getMpSolverExports(), name, problemType);
  }
  static createSolver(solverId) {
    const module = getMpSolverModule(), exports = getMpSolverExports(), handle = withCString(module, solverId, (solverIdPtr) => exports.solverCreateSolver(solverIdPtr));
    return handle === 0 ? null : new NativeMPSolverBackend(module, exports, handle);
  }
  name() {
    return readCString(this.module, this.exports.solverName(this.handle));
  }
  problemType() {
    return this.exports.solverProblemType(this.handle);
  }
  isMip() {
    return this.exports.solverIsMip(this.handle) === 1;
  }
  clear() {
    this.exports.solverClear(this.handle);
  }
  infinity() {
    return this.exports.solverInfinity();
  }
  variable(index) {
    const handle = this.exports.solverVariable(this.handle, index);
    if (handle === 0) throw new Error(`MPSolver.variable: no variable at index ${index}.`);
    return { index, handle };
  }
  variables() {
    return Array.from({ length: this.numVariables() }, (_, index) => this.variable(index));
  }
  lookupVariable(name) {
    const handle = withCString(this.module, name, (namePtr) => this.exports.solverLookupVariable(this.handle, namePtr));
    return handle === 0 ? null : { index: this.exports.variableIndex(handle), handle };
  }
  addVariable(lb, ub, integer, name) {
    const handle = withCString(this.module, name, (namePtr) => this.exports.solverVar(this.handle, lb, ub, integer ? 1 : 0, namePtr));
    if (handle === 0) throw new Error(`MPSolver.Var: failed to create variable '${name}'.`);
    return { index: this.exports.variableIndex(handle), handle };
  }
  variableSolutionValue(ref) {
    return this.exports.variableSolutionValue(nativeVariableHandle(ref));
  }
  variableUnroundedSolutionValue(ref) {
    return this.exports.variableUnroundedSolutionValue(nativeVariableHandle(ref));
  }
  variableReducedCost(ref) {
    return this.exports.variableReducedCost(nativeVariableHandle(ref));
  }
  variableBasisStatus(ref) {
    return this.exports.variableBasisStatus(nativeVariableHandle(ref));
  }
  variableIndex(ref) {
    return this.exports.variableIndex(nativeVariableHandle(ref));
  }
  variableName(ref) {
    return readCString(this.module, this.exports.variableName(nativeVariableHandle(ref)));
  }
  variableLb(ref) {
    return this.exports.variableLb(nativeVariableHandle(ref));
  }
  variableUb(ref) {
    return this.exports.variableUb(nativeVariableHandle(ref));
  }
  setVariableBounds(ref, lb, ub) {
    this.exports.variableSetBounds(nativeVariableHandle(ref), lb, ub);
  }
  setVariableLb(ref, lb) {
    this.exports.variableSetLb(nativeVariableHandle(ref), lb);
  }
  setVariableUb(ref, ub) {
    this.exports.variableSetUb(nativeVariableHandle(ref), ub);
  }
  variableInteger(ref) {
    return this.exports.variableInteger(nativeVariableHandle(ref)) === 1;
  }
  setVariableInteger(ref, integer) {
    this.exports.variableSetInteger(nativeVariableHandle(ref), integer ? 1 : 0);
  }
  variableBranchingPriority(ref) {
    return this.exports.variableBranchingPriority(nativeVariableHandle(ref));
  }
  setVariableBranchingPriority(ref, priority) {
    this.exports.variableSetBranchingPriority(nativeVariableHandle(ref), priority);
  }
  constraint(index) {
    const handle = this.exports.solverConstraint(this.handle, index);
    if (handle === 0) throw new Error(`MPSolver.constraint: no constraint at index ${index}.`);
    return { index, handle };
  }
  constraints() {
    return Array.from({ length: this.numConstraints() }, (_, index) => this.constraint(index));
  }
  lookupConstraint(name) {
    const handle = withCString(this.module, name, (namePtr) => this.exports.solverLookupConstraint(this.handle, namePtr));
    return handle === 0 ? null : { index: this.exports.constraintIndex(handle), handle };
  }
  addConstraint(lb, ub, name) {
    const hasBounds = typeof lb == "number" && typeof ub == "number", handle = withCString(this.module, name, (namePtr) => hasBounds ? this.exports.solverRowConstraint(this.handle, lb, ub, namePtr) : this.exports.solverUnboundedRowConstraint(this.handle, namePtr));
    if (handle === 0) throw new Error(`MPSolver.Constraint: failed to create constraint '${name}'.`);
    return { index: this.exports.constraintIndex(handle), handle };
  }
  setConstraintCoefficient(constraint, variable, coefficient) {
    this.exports.constraintSetCoefficient(nativeConstraintHandle(constraint), nativeVariableHandle(variable), coefficient);
  }
  constraintCoefficient(constraint, variable) {
    return this.exports.constraintGetCoefficient(nativeConstraintHandle(constraint), nativeVariableHandle(variable));
  }
  clearConstraint(constraint) {
    this.exports.constraintClear(nativeConstraintHandle(constraint));
  }
  constraintIndex(ref) {
    return this.exports.constraintIndex(nativeConstraintHandle(ref));
  }
  constraintName(ref) {
    return readCString(this.module, this.exports.constraintName(nativeConstraintHandle(ref)));
  }
  constraintLb(ref) {
    return this.exports.constraintLb(nativeConstraintHandle(ref));
  }
  constraintUb(ref) {
    return this.exports.constraintUb(nativeConstraintHandle(ref));
  }
  setConstraintBounds(ref, lb, ub) {
    this.exports.constraintSetBounds(nativeConstraintHandle(ref), lb, ub);
  }
  setConstraintLb(ref, lb) {
    this.exports.constraintSetLb(nativeConstraintHandle(ref), lb);
  }
  setConstraintUb(ref, ub) {
    this.exports.constraintSetUb(nativeConstraintHandle(ref), ub);
  }
  constraintDualValue(ref) {
    return this.exports.constraintDualValue(nativeConstraintHandle(ref));
  }
  constraintBasisStatus(ref) {
    return this.exports.constraintBasisStatus(nativeConstraintHandle(ref));
  }
  constraintIsLazy(ref) {
    return this.exports.constraintIsLazy(nativeConstraintHandle(ref)) === 1;
  }
  setConstraintIsLazy(ref, laziness) {
    this.exports.constraintSetIsLazy(nativeConstraintHandle(ref), laziness ? 1 : 0);
  }
  clearObjective() {
    this.exports.objectiveClear(this.handle);
  }
  setObjectiveCoefficient(variable, coefficient) {
    this.exports.objectiveSetCoefficient(this.handle, nativeVariableHandle(variable), coefficient);
  }
  objectiveCoefficient(variable) {
    return this.exports.objectiveGetCoefficient(this.handle, nativeVariableHandle(variable));
  }
  setObjectiveOffset(offset) {
    this.exports.objectiveSetOffset(this.handle, offset);
  }
  addObjectiveOffset(offset) {
    this.exports.objectiveAddOffset(this.handle, offset);
  }
  objectiveOffset() {
    return this.exports.objectiveOffset(this.handle);
  }
  setObjectiveDirection(maximize) {
    this.exports.objectiveSetOptimizationDirection(this.handle, maximize ? 1 : 0);
  }
  objectiveValue() {
    return this.exports.objectiveValue(this.handle);
  }
  objectiveBestBound() {
    return this.exports.objectiveBestBound(this.handle);
  }
  objectiveMaximization() {
    return this.exports.objectiveMaximization(this.handle) === 1;
  }
  async solve(parameters) {
    return parameters ? await this.module.ccall(
      "mp_solver_solve_with_parameters",
      "number",
      ["number", "number"],
      [this.handle, parameters.nativeHandle()],
      { async: !0 }
    ) : await this.module.ccall(
      "mp_solver_solve",
      "number",
      ["number"],
      [this.handle],
      { async: !0 }
    );
  }
  exportModelProto() {
    return readNativeBytes(this.module, (lenPtr) => this.exports.solverExportModelProto(this.handle, lenPtr));
  }
  exportModelRequestProto(options = {}) {
    const solverType = options.solverType ?? this.problemType(), parameters = options.solverSpecificParameters ?? "";
    return withCString(this.module, parameters, (parametersPtr) => readNativeBytes(this.module, (lenPtr) => this.exports.solverExportModelRequestProto(
      this.handle,
      solverType,
      options.timeLimitSeconds ?? 0,
      options.enableOutput ? 1 : 0,
      parametersPtr,
      lenPtr
    )));
  }
  async loadSolutionFromProto(response, tolerance) {
    const responseBytes = response instanceof Uint8Array ? response : await encodeMPSolutionResponse(response), responsePtr = copyBytesToHeap(this.module, responseBytes);
    try {
      return this.exports.solverLoadSolutionProto(this.handle, responsePtr, responseBytes.length, tolerance) === 1;
    } finally {
      responsePtr && this.module._free(responsePtr);
    }
  }
  verifySolution(tolerance, logErrors) {
    return this.exports.solverVerifySolution(this.handle, tolerance, logErrors ? 1 : 0) === 1;
  }
  reset() {
    this.exports.solverReset(this.handle);
  }
  interruptSolve() {
    return this.exports.solverInterruptSolve(this.handle) === 1;
  }
  nextSolution() {
    return this.exports.solverNextSolution(this.handle) === 1;
  }
  enableOutput() {
    this.exports.solverEnableOutput(this.handle);
  }
  suppressOutput() {
    this.exports.solverSuppressOutput(this.handle);
  }
  outputIsEnabled() {
    return this.exports.solverOutputIsEnabled(this.handle) === 1;
  }
  setTimeLimit(milliseconds) {
    this.exports.solverSetTimeLimit(this.handle, BigInt(Math.trunc(milliseconds)));
  }
  timeLimit() {
    return toNumber(this.exports.solverTimeLimit(this.handle));
  }
  setNumThreads(numThreads) {
    return this.exports.solverSetNumThreads(this.handle, numThreads) === 1;
  }
  getNumThreads() {
    return this.exports.solverGetNumThreads(this.handle);
  }
  setSolverSpecificParametersAsString(parameters) {
    return withCString(this.module, parameters, (parametersPtr) => this.exports.solverSetSolverSpecificParametersAsString(this.handle, parametersPtr) === 1);
  }
  getSolverSpecificParametersAsString() {
    return this.exports.solverGetSolverSpecificParametersAsString(this.handle), readCString(this.module, this.exports.lastStringResult());
  }
  solverVersion() {
    return readCString(this.module, this.exports.solverSolverVersion(this.handle));
  }
  computeConstraintActivities() {
    return Array.from({ length: this.numConstraints() }, (_, index) => this.exports.solverConstraintActivity(this.handle, index));
  }
  computeExactConditionNumber() {
    return this.exports.solverComputeExactConditionNumber(this.handle);
  }
  setHint(variables, values) {
    const variableBytes = variables.length * Int32Array.BYTES_PER_ELEMENT, valueBytes = values.length * Float64Array.BYTES_PER_ELEMENT, variablePtr = this.module._malloc(variableBytes), valuePtr = this.module._malloc(valueBytes);
    try {
      new Int32Array(this.module.HEAPU8.buffer, variablePtr, variables.length).set(variables.map(nativeVariableHandle)), new Float64Array(this.module.HEAPU8.buffer, valuePtr, values.length).set(values), this.exports.solverSetHint(this.handle, variablePtr, valuePtr, variables.length);
    } finally {
      this.module._free(variablePtr), this.module._free(valuePtr);
    }
  }
  exportModelAsLpFormat(obfuscate) {
    return this.exports.solverExportModelAsLpFormat(this.handle, obfuscate ? 1 : 0), readCString(this.module, this.exports.lastStringResult());
  }
  exportModelAsMpsFormat(fixedFormat, obfuscate) {
    return this.exports.solverExportModelAsMpsFormat(this.handle, fixedFormat ? 1 : 0, obfuscate ? 1 : 0), readCString(this.module, this.exports.lastStringResult());
  }
  numVariables() {
    return this.exports.solverNumVariables(this.handle);
  }
  numConstraints() {
    return this.exports.solverNumConstraints(this.handle);
  }
  wallTime() {
    return toNumber(this.exports.solverWallTime(this.handle));
  }
  iterations() {
    return toNumber(this.exports.solverIterations(this.handle));
  }
  nodes() {
    return toNumber(this.exports.solverNodes(this.handle));
  }
  delete() {
    this.handle !== 0 && (this.exports.solverDelete(this.handle), this.handle = 0);
  }
}
class BridgeMPSolverBackend {
  constructor(name, problemType) {
    __publicField(this, "state");
    this.state = createWorkerSolverState(name, problemType);
  }
  variableState(ref) {
    const variable = this.state.variables[ref.index];
    if (!variable) throw new Error(`MPSolver.variable: no variable at index ${ref.index}.`);
    return variable;
  }
  constraintState(ref) {
    const constraint = this.state.constraints[ref.index];
    if (!constraint) throw new Error(`MPSolver.constraint: no constraint at index ${ref.index}.`);
    return constraint;
  }
  name() {
    return this.state.name;
  }
  problemType() {
    return this.state.problemType;
  }
  isMip() {
    return workerProblemIsMip(this.state.problemType);
  }
  clear() {
    this.state.variables = [], this.state.constraints = [], this.state.objective.coeffs.clear(), this.state.objective.offset = 0, this.state.hints = null, resetWorkerSolution(this.state);
  }
  infinity() {
    return Number.POSITIVE_INFINITY;
  }
  variable(index) {
    return this.variableState({ index }), { index };
  }
  variables() {
    return this.state.variables.map((variable) => ({ index: variable.index }));
  }
  lookupVariable(name) {
    const variable = this.state.variables.find((candidate) => candidate.name === name);
    return variable ? { index: variable.index } : null;
  }
  addVariable(lb, ub, integer, name) {
    const variable = {
      index: this.state.variables.length,
      name,
      lb,
      ub,
      integer,
      branchingPriority: 0,
      solutionValue: 0,
      unroundedSolutionValue: 0,
      reducedCost: 0,
      basisStatus: 0 /* FREE */
    };
    return this.state.variables.push(variable), { index: variable.index };
  }
  variableSolutionValue(ref) {
    return this.variableState(ref).solutionValue;
  }
  variableUnroundedSolutionValue(ref) {
    return this.variableState(ref).unroundedSolutionValue;
  }
  variableReducedCost(ref) {
    return this.variableState(ref).reducedCost;
  }
  variableBasisStatus(ref) {
    return this.variableState(ref).basisStatus;
  }
  variableIndex(ref) {
    return this.variableState(ref).index;
  }
  variableName(ref) {
    return this.variableState(ref).name;
  }
  variableLb(ref) {
    return this.variableState(ref).lb;
  }
  variableUb(ref) {
    return this.variableState(ref).ub;
  }
  setVariableBounds(ref, lb, ub) {
    const variable = this.variableState(ref);
    variable.lb = lb, variable.ub = ub;
  }
  setVariableLb(ref, lb) {
    this.variableState(ref).lb = lb;
  }
  setVariableUb(ref, ub) {
    this.variableState(ref).ub = ub;
  }
  variableInteger(ref) {
    return this.variableState(ref).integer;
  }
  setVariableInteger(ref, integer) {
    this.variableState(ref).integer = integer;
  }
  variableBranchingPriority(ref) {
    return this.variableState(ref).branchingPriority;
  }
  setVariableBranchingPriority(ref, priority) {
    this.variableState(ref).branchingPriority = priority;
  }
  constraint(index) {
    return this.constraintState({ index }), { index };
  }
  constraints() {
    return this.state.constraints.map((constraint) => ({ index: constraint.index }));
  }
  lookupConstraint(name) {
    const constraint = this.state.constraints.find((candidate) => candidate.name === name);
    return constraint ? { index: constraint.index } : null;
  }
  addConstraint(lb, ub, name) {
    const constraint = {
      index: this.state.constraints.length,
      name,
      lb: lb ?? Number.NEGATIVE_INFINITY,
      ub: ub ?? Number.POSITIVE_INFINITY,
      coeffs: /* @__PURE__ */ new Map(),
      dualValue: 0,
      basisStatus: 0 /* FREE */,
      lazy: !1
    };
    return this.state.constraints.push(constraint), { index: constraint.index };
  }
  setConstraintCoefficient(constraintRef, variableRef, coefficient) {
    const constraint = this.constraintState(constraintRef);
    coefficient === 0 ? constraint.coeffs.delete(variableRef.index) : constraint.coeffs.set(variableRef.index, coefficient);
  }
  constraintCoefficient(constraintRef, variableRef) {
    return this.constraintState(constraintRef).coeffs.get(variableRef.index) ?? 0;
  }
  clearConstraint(constraint) {
    this.constraintState(constraint).coeffs.clear();
  }
  constraintIndex(ref) {
    return this.constraintState(ref).index;
  }
  constraintName(ref) {
    return this.constraintState(ref).name;
  }
  constraintLb(ref) {
    return this.constraintState(ref).lb;
  }
  constraintUb(ref) {
    return this.constraintState(ref).ub;
  }
  setConstraintBounds(ref, lb, ub) {
    const constraint = this.constraintState(ref);
    constraint.lb = lb, constraint.ub = ub;
  }
  setConstraintLb(ref, lb) {
    this.constraintState(ref).lb = lb;
  }
  setConstraintUb(ref, ub) {
    this.constraintState(ref).ub = ub;
  }
  constraintDualValue(ref) {
    return this.constraintState(ref).dualValue;
  }
  constraintBasisStatus(ref) {
    return this.constraintState(ref).basisStatus;
  }
  constraintIsLazy(ref) {
    return this.constraintState(ref).lazy;
  }
  setConstraintIsLazy(ref, laziness) {
    this.constraintState(ref).lazy = laziness;
  }
  clearObjective() {
    this.state.objective.coeffs.clear(), this.state.objective.offset = 0, this.state.objective.value = 0, this.state.objective.bestBound = 0;
  }
  setObjectiveCoefficient(variable, coefficient) {
    coefficient === 0 ? this.state.objective.coeffs.delete(variable.index) : this.state.objective.coeffs.set(variable.index, coefficient);
  }
  objectiveCoefficient(variable) {
    return this.state.objective.coeffs.get(variable.index) ?? 0;
  }
  setObjectiveOffset(offset) {
    this.state.objective.offset = offset;
  }
  addObjectiveOffset(offset) {
    this.state.objective.offset += offset;
  }
  objectiveOffset() {
    return this.state.objective.offset;
  }
  setObjectiveDirection(maximize) {
    this.state.objective.maximize = maximize;
  }
  objectiveValue() {
    return this.state.objective.value;
  }
  objectiveBestBound() {
    return this.state.objective.bestBound;
  }
  objectiveMaximization() {
    return this.state.objective.maximize;
  }
  async solve() {
    const started = Date.now(), result = await MPSolver.solveModelRequest(
      workerModelRequest(this.state),
      { numThreads: this.state.numThreads }
    );
    return applyWorkerSolutionResponse(this.state, result.response), this.state.wallTimeMs = Math.max(this.state.wallTimeMs, Date.now() - started), workerStatusToResultStatus(result.response.status);
  }
  exportModelProto() {
    return encodeMPModel(workerModelProto(this.state));
  }
  exportModelRequestProto(options = {}) {
    return encodeMPModelRequest(workerModelRequest(this.state, options));
  }
  async loadSolutionFromProto(response, _tolerance) {
    const decoded = response instanceof Uint8Array ? await decodeMPSolutionResponse(response) : response;
    return applyWorkerSolutionResponse(this.state, decoded);
  }
  verifySolution(tolerance) {
    if (!this.state.solutionLoaded) return !1;
    for (const variable of this.state.variables)
      if (variable.solutionValue < variable.lb - tolerance || variable.solutionValue > variable.ub + tolerance || variable.integer && Math.abs(variable.solutionValue - Math.round(variable.solutionValue)) > tolerance) return !1;
    for (const constraint of this.state.constraints) {
      const activity = workerConstraintActivity(this.state, constraint);
      if (activity < constraint.lb - tolerance || activity > constraint.ub + tolerance) return !1;
    }
    return !0;
  }
  reset() {
    resetWorkerSolution(this.state);
  }
  interruptSolve() {
    return !1;
  }
  nextSolution() {
    return !1;
  }
  enableOutput() {
    this.state.outputEnabled = !0;
  }
  suppressOutput() {
    this.state.outputEnabled = !1;
  }
  outputIsEnabled() {
    return this.state.outputEnabled;
  }
  setTimeLimit(milliseconds) {
    this.state.timeLimitMs = Math.trunc(milliseconds);
  }
  timeLimit() {
    return this.state.timeLimitMs;
  }
  setNumThreads(numThreads) {
    return !Number.isInteger(numThreads) || numThreads < 1 || !workerProblemSupportsNumThreads(this.state.problemType) ? !1 : (this.state.numThreads = numThreads, !0);
  }
  getNumThreads() {
    return this.state.numThreads;
  }
  setSolverSpecificParametersAsString(parameters) {
    return this.state.solverSpecificParameters = parameters, !0;
  }
  getSolverSpecificParametersAsString() {
    return this.state.solverSpecificParameters;
  }
  solverVersion() {
    return "OR-Tools worker bridge MPSolver";
  }
  computeConstraintActivities() {
    return this.state.constraints.map((constraint) => workerConstraintActivity(this.state, constraint));
  }
  computeExactConditionNumber() {
    return 0;
  }
  setHint(variables, values) {
    this.state.hints = {
      varIndex: variables.map((variable) => variable.index),
      varValue: [...values]
    };
  }
  exportModelAsLpFormat(_obfuscate) {
    return `${this.state.objective.maximize ? "Maximize" : "Minimize"}
 obj: ${this.state.name}
Subject To
${this.state.constraints.map((c) => ` ${c.name}`).join(`
`)}
End
`;
  }
  exportModelAsMpsFormat(_fixedFormat, _obfuscate) {
    return `NAME          ${this.state.name}
ROWS
COLUMNS
RHS
BOUNDS
ENDATA
`;
  }
  numVariables() {
    return this.state.variables.length;
  }
  numConstraints() {
    return this.state.constraints.length;
  }
  wallTime() {
    return this.state.wallTimeMs;
  }
  iterations() {
    return this.state.iterations;
  }
  nodes() {
    return this.state.nodes;
  }
  delete() {
    this.state.deleted = !0, this.clear();
  }
}
class MPVariable {
  constructor(backend, ref) {
    __publicField(this, "backend", backend);
    __publicField(this, "ref", ref);
  }
  SolutionValue() {
    return this.solution_value();
  }
  solution_value() {
    return this.backend.variableSolutionValue(this.ref);
  }
  unrounded_solution_value() {
    return this.backend.variableUnroundedSolutionValue(this.ref);
  }
  ReducedCost() {
    return this.reduced_cost();
  }
  reduced_cost() {
    return this.backend.variableReducedCost(this.ref);
  }
  basis_status() {
    return this.backend.variableBasisStatus(this.ref);
  }
  index() {
    return this.backend.variableIndex(this.ref);
  }
  name() {
    return this.backend.variableName(this.ref);
  }
  Lb() {
    return this.backend.variableLb(this.ref);
  }
  Ub() {
    return this.backend.variableUb(this.ref);
  }
  SetBounds(lb, ub) {
    this.backend.setVariableBounds(this.ref, lb, ub);
  }
  SetLb(lb) {
    this.SetLB(lb);
  }
  SetLB(lb) {
    this.backend.setVariableLb(this.ref, lb);
  }
  SetUb(ub) {
    this.SetUB(ub);
  }
  SetUB(ub) {
    this.backend.setVariableUb(this.ref, ub);
  }
  Integer() {
    return this.backend.variableInteger(this.ref);
  }
  SetInteger(integer) {
    this.backend.setVariableInteger(this.ref, integer);
  }
  branching_priority() {
    return this.backend.variableBranchingPriority(this.ref);
  }
  SetBranchingPriority(priority) {
    this.backend.setVariableBranchingPriority(this.ref, priority);
  }
  toString() {
    return this.name();
  }
}
class MPConstraint {
  constructor(backend, ref) {
    __publicField(this, "backend", backend);
    __publicField(this, "ref", ref);
  }
  SetCoefficient(variable, coefficient) {
    this.backend.setConstraintCoefficient(this.ref, variable.ref, coefficient);
  }
  GetCoefficient(variable) {
    return this.backend.constraintCoefficient(this.ref, variable.ref);
  }
  Clear() {
    this.backend.clearConstraint(this.ref);
  }
  index() {
    return this.backend.constraintIndex(this.ref);
  }
  name() {
    return this.backend.constraintName(this.ref);
  }
  Lb() {
    return this.backend.constraintLb(this.ref);
  }
  Ub() {
    return this.backend.constraintUb(this.ref);
  }
  SetBounds(lb, ub) {
    this.backend.setConstraintBounds(this.ref, lb, ub);
  }
  SetLb(lb) {
    this.SetLB(lb);
  }
  SetLB(lb) {
    this.backend.setConstraintLb(this.ref, lb);
  }
  SetUb(ub) {
    this.SetUB(ub);
  }
  SetUB(ub) {
    this.backend.setConstraintUb(this.ref, ub);
  }
  DualValue() {
    return this.dual_value();
  }
  dual_value() {
    return this.backend.constraintDualValue(this.ref);
  }
  basis_status() {
    return this.backend.constraintBasisStatus(this.ref);
  }
  is_lazy() {
    return this.backend.constraintIsLazy(this.ref);
  }
  set_is_lazy(laziness) {
    this.backend.setConstraintIsLazy(this.ref, laziness);
  }
}
class MPObjective {
  constructor(backend) {
    __publicField(this, "backend", backend);
  }
  Clear() {
    this.backend.clearObjective();
  }
  SetCoefficient(variable, coefficient) {
    this.backend.setObjectiveCoefficient(variable.ref, coefficient);
  }
  GetCoefficient(variable) {
    return this.backend.objectiveCoefficient(variable.ref);
  }
  SetOffset(offset) {
    this.backend.setObjectiveOffset(offset);
  }
  AddOffset(offset) {
    this.backend.addObjectiveOffset(offset);
  }
  Offset() {
    return this.offset();
  }
  offset() {
    return this.backend.objectiveOffset();
  }
  SetOptimizationDirection(maximize) {
    this.backend.setObjectiveDirection(maximize);
  }
  SetMinimization() {
    this.backend.setObjectiveDirection(!1);
  }
  SetMaximization() {
    this.backend.setObjectiveDirection(!0);
  }
  Value() {
    return this.backend.objectiveValue();
  }
  BestBound() {
    return this.backend.objectiveBestBound();
  }
  maximization() {
    return this.backend.objectiveMaximization();
  }
  minimization() {
    return !this.backend.objectiveMaximization();
  }
}
class MPSolverParameters {
  constructor() {
    __publicField(this, "backend");
    this.backend = shouldUseMPSolverBridge() ? new BridgeMPSolverParametersBackend() : new NativeMPSolverParametersBackend();
  }
  get nativeHandle() {
    return this.backend.nativeHandle();
  }
  SetDoubleParam(param, value) {
    this.backend.setDoubleParam(param, value);
  }
  GetDoubleParam(param) {
    return this.backend.getDoubleParam(param);
  }
  ResetDoubleParam(param) {
    this.backend.resetDoubleParam(param);
  }
  SetIntegerParam(param, value) {
    this.backend.setIntegerParam(param, value);
  }
  GetIntegerParam(param) {
    return this.backend.getIntegerParam(param);
  }
  ResetIntegerParam(param) {
    this.backend.resetIntegerParam(param);
  }
  Reset() {
    this.backend.reset();
  }
  delete() {
    this.backend.delete();
  }
}
__publicField(MPSolverParameters, "RELATIVE_MIP_GAP", 0 /* RELATIVE_MIP_GAP */), __publicField(MPSolverParameters, "PRIMAL_TOLERANCE", 1 /* PRIMAL_TOLERANCE */), __publicField(MPSolverParameters, "DUAL_TOLERANCE", 2 /* DUAL_TOLERANCE */), __publicField(MPSolverParameters, "PRESOLVE", 1e3 /* PRESOLVE */), __publicField(MPSolverParameters, "LP_ALGORITHM", 1001 /* LP_ALGORITHM */), __publicField(MPSolverParameters, "INCREMENTALITY", 1002 /* INCREMENTALITY */), __publicField(MPSolverParameters, "SCALING", 1003 /* SCALING */), __publicField(MPSolverParameters, "PRESOLVE_OFF", 0 /* PRESOLVE_OFF */), __publicField(MPSolverParameters, "PRESOLVE_ON", 1 /* PRESOLVE_ON */), __publicField(MPSolverParameters, "DUAL", 10 /* DUAL */), __publicField(MPSolverParameters, "PRIMAL", 11 /* PRIMAL */), __publicField(MPSolverParameters, "BARRIER", 12 /* BARRIER */), __publicField(MPSolverParameters, "INCREMENTALITY_OFF", 0 /* INCREMENTALITY_OFF */), __publicField(MPSolverParameters, "INCREMENTALITY_ON", 1 /* INCREMENTALITY_ON */), __publicField(MPSolverParameters, "SCALING_OFF", 0 /* SCALING_OFF */), __publicField(MPSolverParameters, "SCALING_ON", 1 /* SCALING_ON */), __publicField(MPSolverParameters, "kDefaultRelativeMipGap", 1e-4), __publicField(MPSolverParameters, "kDefaultPrimalTolerance", 1e-7), __publicField(MPSolverParameters, "kDefaultDualTolerance", 1e-7), __publicField(MPSolverParameters, "kDefaultPresolve", 1 /* PRESOLVE_ON */), __publicField(MPSolverParameters, "kDefaultIncrementality", 1 /* INCREMENTALITY_ON */);
const _MPSolver = class _MPSolver {
  constructor(nameOrModule, problemTypeOrExports, maybeHandle) {
    __publicField(this, "ready", Promise.resolve());
    __publicField(this, "backend");
    __publicField(this, "objective");
    typeof nameOrModule == "string" ? this.backend = shouldUseMPSolverBridge() ? new BridgeMPSolverBackend(nameOrModule, problemTypeOrExports) : NativeMPSolverBackend.create(nameOrModule, problemTypeOrExports) : this.backend = new NativeMPSolverBackend(nameOrModule, problemTypeOrExports, maybeHandle ?? 0), this.objective = new MPObjective(this.backend);
  }
  static CreateSolver(solverId) {
    if (shouldUseMPSolverBridge()) {
      const problemType = workerParseSolverType(solverId);
      return problemType !== null && workerSupportsProblemType(problemType) ? new _MPSolver(solverId, problemType) : null;
    }
    const backend = NativeMPSolverBackend.createSolver(solverId);
    if (!backend) return null;
    const solver = Object.create(_MPSolver.prototype);
    return Object.defineProperty(solver, "backend", { value: backend }), Object.defineProperty(solver, "objective", { value: new MPObjective(backend) }), Object.defineProperty(solver, "ready", { value: Promise.resolve() }), solver;
  }
  static Infinity() {
    return shouldUseMPSolverBridge() ? Number.POSITIVE_INFINITY : getMpSolverExports().solverInfinity();
  }
  static SupportsProblemType(problemType) {
    return shouldUseMPSolverBridge() ? workerSupportsProblemType(problemType) : getMpSolverExports().solverSupportsProblemType(problemType) === 1;
  }
  static ParseSolverType(solverId) {
    if (shouldUseMPSolverBridge())
      return workerParseSolverType(solverId);
    const module = getMpSolverModule(), exports = getMpSolverExports(), problemType = withCString(module, solverId, (solverIdPtr) => exports.solverParseSolverType(solverIdPtr));
    return problemType < 0 ? null : problemType;
  }
  static ParseAndCheckSupportForProblemType(solverId) {
    const problemType = _MPSolver.ParseSolverType(solverId);
    return problemType === null ? null : _MPSolver.SupportsProblemType(problemType) ? problemType : null;
  }
  static setWorkerBridgeEnabled(enabled) {
    setMPSolverWorkerBridgeEnabled(enabled);
  }
  static isWorkerBridgeEnabled() {
    return isMPSolverWorkerBridgeEnabled();
  }
  static isWorkerBridgeAvailable() {
    return isMPSolverWorkerBridgeAvailable();
  }
  static getLinearSolverSchemas() {
    return getLinearSolverSchemas();
  }
  static createModelRequest(request) {
    return encodeMPModelRequest(request);
  }
  static decodeSolutionResponse(bytes) {
    return decodeMPSolutionResponse(bytes);
  }
  static createSolutionResponse(response) {
    return encodeMPSolutionResponse(response);
  }
  static async solveModelRequest(request, options = {}) {
    const requestBytes = request instanceof Uint8Array ? request : await encodeMPModelRequest(request), bytes = await solveModelRequestBytes(requestBytes, options);
    return {
      bytes,
      response: await decodeMPSolutionResponse(bytes)
    };
  }
  Name() {
    return this.backend.name();
  }
  ProblemType() {
    return this.backend.problemType();
  }
  IsMip() {
    return this.IsMIP();
  }
  IsMIP() {
    return this.backend.isMip();
  }
  Clear() {
    this.backend.clear();
  }
  infinity() {
    return this.backend.infinity();
  }
  variable(index) {
    return new MPVariable(this.backend, this.backend.variable(index));
  }
  variables() {
    return this.backend.variables().map((ref) => new MPVariable(this.backend, ref));
  }
  LookupVariableOrNull(name) {
    const ref = this.backend.lookupVariable(name);
    return ref ? new MPVariable(this.backend, ref) : null;
  }
  LookupVariable(name) {
    return this.LookupVariableOrNull(name);
  }
  Var(lb, ub, integer, name) {
    return new MPVariable(this.backend, this.backend.addVariable(lb, ub, integer, name));
  }
  NumVar(lb, ub, name) {
    return this.Var(lb, ub, !1, name);
  }
  IntVar(lb, ub, name) {
    return this.Var(lb, ub, !0, name);
  }
  BoolVar(name) {
    return this.Var(0, 1, !0, name);
  }
  constraint(index) {
    return new MPConstraint(this.backend, this.backend.constraint(index));
  }
  constraints() {
    return this.backend.constraints().map((ref) => new MPConstraint(this.backend, ref));
  }
  LookupConstraintOrNull(name) {
    const ref = this.backend.lookupConstraint(name);
    return ref ? new MPConstraint(this.backend, ref) : null;
  }
  LookupConstraint(name) {
    return this.LookupConstraintOrNull(name);
  }
  Constraint(lbOrName, ub, name = "") {
    const hasBounds = typeof lbOrName == "number" && typeof ub == "number", constraintName = typeof lbOrName == "string" ? lbOrName : name;
    return new MPConstraint(
      this.backend,
      this.backend.addConstraint(hasBounds ? lbOrName : null, hasBounds ? ub : null, constraintName)
    );
  }
  RowConstraint(lbOrName, ub, name = "") {
    if (typeof lbOrName == "number") {
      if (typeof ub != "number") throw new Error("MPSolver.RowConstraint: upper bound is required.");
      return this.Constraint(lbOrName, ub, name);
    }
    return this.Constraint(lbOrName ?? "");
  }
  Objective() {
    return this.objective;
  }
  async Solve(parameters) {
    return this.backend.solve(parameters?.backend);
  }
  exportModelProto() {
    return this.backend.exportModelProto();
  }
  exportModelRequestProto(options = {}) {
    return this.backend.exportModelRequestProto(options);
  }
  async SolveWithProto(options = {}) {
    const requestBytes = await this.exportModelRequestProto(options), result = await _MPSolver.solveModelRequest(requestBytes, options);
    let loaded = !1;
    return (options.loadSolution ?? !0) && (loaded = await this.LoadSolutionFromProto(result.bytes, options.tolerance)), { ...result, loaded };
  }
  async LoadSolutionFromProto(response = {}, tolerance = 1e-7) {
    return this.backend.loadSolutionFromProto(response, tolerance);
  }
  VerifySolution(tolerance, logErrors) {
    return this.backend.verifySolution(tolerance, logErrors);
  }
  Reset() {
    this.backend.reset();
  }
  InterruptSolve() {
    return this.backend.interruptSolve();
  }
  NextSolution() {
    return this.backend.nextSolution();
  }
  EnableOutput() {
    this.backend.enableOutput();
  }
  SuppressOutput() {
    this.backend.suppressOutput();
  }
  OutputIsEnabled() {
    return this.backend.outputIsEnabled();
  }
  SetTimeLimit(milliseconds) {
    this.set_time_limit(milliseconds);
  }
  set_time_limit(milliseconds) {
    this.backend.setTimeLimit(milliseconds);
  }
  time_limit() {
    return this.backend.timeLimit();
  }
  SetNumThreads(numThreads) {
    return this.backend.setNumThreads(numThreads);
  }
  GetNumThreads() {
    return this.backend.getNumThreads();
  }
  SetSolverSpecificParametersAsString(parameters) {
    return this.backend.setSolverSpecificParametersAsString(parameters);
  }
  GetSolverSpecificParametersAsString() {
    return this.backend.getSolverSpecificParametersAsString();
  }
  SolverVersion() {
    return this.backend.solverVersion();
  }
  ComputeConstraintActivities() {
    return this.backend.computeConstraintActivities();
  }
  ComputeExactConditionNumber() {
    return this.backend.computeExactConditionNumber();
  }
  SetHint(variables, values) {
    if (variables.length !== values.length)
      throw new Error(`MPSolver.SetHint: variable/value length mismatch (${variables.length} !== ${values.length}).`);
    this.backend.setHint(variables.map((variable) => variable.ref), values);
  }
  ExportModelAsLpFormat(obfuscate) {
    return this.backend.exportModelAsLpFormat(obfuscate);
  }
  ExportModelAsMpsFormat(fixedFormat, obfuscate) {
    return this.backend.exportModelAsMpsFormat(fixedFormat, obfuscate);
  }
  NumVariables() {
    return this.backend.numVariables();
  }
  NumConstraints() {
    return this.backend.numConstraints();
  }
  WallTime() {
    return this.backend.wallTime();
  }
  wall_time() {
    return this.WallTime();
  }
  Iterations() {
    return this.backend.iterations();
  }
  iterations() {
    return this.Iterations();
  }
  nodes() {
    return this.backend.nodes();
  }
  delete() {
    this.backend.delete();
  }
};
__publicField(_MPSolver, "CLP_LINEAR_PROGRAMMING", 0 /* CLP_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "GLPK_LINEAR_PROGRAMMING", 1 /* GLPK_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "GLOP_LINEAR_PROGRAMMING", 2 /* GLOP_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "PDLP_LINEAR_PROGRAMMING", 8 /* PDLP_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "HIGHS_LINEAR_PROGRAMMING", 15 /* HIGHS_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "SCIP_MIXED_INTEGER_PROGRAMMING", 3 /* SCIP_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "GLPK_MIXED_INTEGER_PROGRAMMING", 4 /* GLPK_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "CBC_MIXED_INTEGER_PROGRAMMING", 5 /* CBC_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "HIGHS_MIXED_INTEGER_PROGRAMMING", 16 /* HIGHS_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "GUROBI_LINEAR_PROGRAMMING", 6 /* GUROBI_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "GUROBI_MIXED_INTEGER_PROGRAMMING", 7 /* GUROBI_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "CPLEX_LINEAR_PROGRAMMING", 10 /* CPLEX_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "CPLEX_MIXED_INTEGER_PROGRAMMING", 11 /* CPLEX_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "XPRESS_LINEAR_PROGRAMMING", 101 /* XPRESS_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "XPRESS_MIXED_INTEGER_PROGRAMMING", 102 /* XPRESS_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "COPT_LINEAR_PROGRAMMING", 103 /* COPT_LINEAR_PROGRAMMING */), __publicField(_MPSolver, "COPT_MIXED_INTEGER_PROGRAMMING", 104 /* COPT_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "BOP_INTEGER_PROGRAMMING", 12 /* BOP_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "SAT_INTEGER_PROGRAMMING", 14 /* SAT_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "KNAPSACK_MIXED_INTEGER_PROGRAMMING", 13 /* KNAPSACK_MIXED_INTEGER_PROGRAMMING */), __publicField(_MPSolver, "OPTIMAL", 0 /* OPTIMAL */), __publicField(_MPSolver, "FEASIBLE", 1 /* FEASIBLE */), __publicField(_MPSolver, "INFEASIBLE", 2 /* INFEASIBLE */), __publicField(_MPSolver, "UNBOUNDED", 3 /* UNBOUNDED */), __publicField(_MPSolver, "ABNORMAL", 4 /* ABNORMAL */), __publicField(_MPSolver, "MODEL_INVALID", 5 /* MODEL_INVALID */), __publicField(_MPSolver, "NOT_SOLVED", 6 /* NOT_SOLVED */), __publicField(_MPSolver, "FREE", 0 /* FREE */), __publicField(_MPSolver, "AT_LOWER_BOUND", 1 /* AT_LOWER_BOUND */), __publicField(_MPSolver, "AT_UPPER_BOUND", 2 /* AT_UPPER_BOUND */), __publicField(_MPSolver, "FIXED_VALUE", 3 /* FIXED_VALUE */), __publicField(_MPSolver, "BASIC", 4 /* BASIC */);
let MPSolver = _MPSolver;
export {
  BasisStatus,
  DoubleParam,
  IncrementalityValues,
  IntegerParam,
  KnapsackSolver,
  KnapsackSolverType,
  LpAlgorithmValues,
  MPConstraint,
  MPObjective,
  MPSolver,
  MPSolverParameters,
  MPSolverResultStatus,
  MPVariable,
  OptimizationProblemType,
  PresolveValues,
  ScalingValues,
  initKnapsack,
  initMPSolver,
  isMPSolverWorkerBridgeAvailable,
  isMPSolverWorkerBridgeEnabled,
  setMPSolverWorkerBridgeEnabled
};
