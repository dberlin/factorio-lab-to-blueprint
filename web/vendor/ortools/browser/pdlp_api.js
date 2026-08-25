var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);
import { loadPdlpRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
let pdlpModulePromise = null, pdlpModule = null;
const terminationReasonNames = {
  0: "TERMINATION_REASON_UNSPECIFIED",
  1: "TERMINATION_REASON_OPTIMAL",
  2: "TERMINATION_REASON_PRIMAL_INFEASIBLE",
  3: "TERMINATION_REASON_DUAL_INFEASIBLE",
  4: "TERMINATION_REASON_TIME_LIMIT",
  5: "TERMINATION_REASON_ITERATION_LIMIT",
  6: "TERMINATION_REASON_NUMERICAL_ERROR",
  7: "TERMINATION_REASON_OTHER",
  8: "TERMINATION_REASON_KKT_MATRIX_PASS_LIMIT",
  9: "TERMINATION_REASON_INVALID_PROBLEM",
  10: "TERMINATION_REASON_INVALID_PARAMETER",
  11: "TERMINATION_REASON_PRIMAL_OR_DUAL_INFEASIBLE",
  12: "TERMINATION_REASON_INTERRUPTED_BY_USER",
  13: "TERMINATION_REASON_INVALID_INITIAL_SOLUTION"
};
async function loadPdlpModule() {
  return pdlpModulePromise || (pdlpModulePromise = loadPdlpRuntime().then((module) => (pdlpModule = module, module))), pdlpModulePromise;
}
function getPdlpModule() {
  if (!pdlpModule)
    throw new Error("initPdlp() must be awaited before using the synchronous PDLP API.");
  return pdlpModule;
}
async function initPdlp() {
  shouldUseWorkerBridge() || await loadPdlpModule();
}
function copyBytesToHeap(module, bytes) {
  if (!bytes.length) return 0;
  const ptr = module._malloc(bytes.length);
  return module.HEAPU8.set(bytes, ptr), ptr;
}
function readUint32LE(buffer, ptr) {
  return new DataView(buffer, ptr, 4).getUint32(0, !0);
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
async function runWithBytes(bytes, fn) {
  const module = getPdlpModule(), ptr = copyBytesToHeap(module, bytes);
  try {
    return await fn(module, ptr, bytes.length);
  } finally {
    ptr && module._free(ptr);
  }
}
async function runPdlpWorker(operation, bytes, options = {}) {
  const response = await postWorkerRequest({
    type: "pdlp",
    id: nextWorkerBridgeRequestId(),
    operation,
    bytes,
    relaxIntegerVariables: options.relaxIntegerVariables,
    includeNames: options.includeNames
  });
  return { bytes: response.bytes, value: response.value };
}
class BinaryWriter {
  constructor() {
    __publicField(this, "parts", []);
  }
  u8(value) {
    this.parts.push(Uint8Array.of(value & 255));
  }
  u32(value) {
    const bytes = new Uint8Array(4);
    new DataView(bytes.buffer).setUint32(0, value, !0), this.parts.push(bytes);
  }
  double(value) {
    const bytes = new Uint8Array(8);
    new DataView(bytes.buffer).setFloat64(0, value, !0), this.parts.push(bytes);
  }
  string(value) {
    const bytes = new TextEncoder().encode(value);
    this.u32(bytes.length), this.parts.push(bytes);
  }
  doubles(values) {
    this.u32(values.length);
    for (const value of values) this.double(value);
  }
  strings(values) {
    this.u32(values.length);
    for (const value of values) this.string(value);
  }
  finish() {
    const size = this.parts.reduce((sum, part) => sum + part.length, 0), output = new Uint8Array(size);
    let offset = 0;
    for (const part of this.parts)
      output.set(part, offset), offset += part.length;
    return output;
  }
}
class BinaryReader {
  constructor(bytes) {
    __publicField(this, "bytes", bytes);
    __publicField(this, "offset", 0);
  }
  u8() {
    return this.bytes[this.offset++] ?? 0;
  }
  u32() {
    const value = new DataView(this.bytes.buffer, this.bytes.byteOffset + this.offset, 4).getUint32(0, !0);
    return this.offset += 4, value;
  }
  double() {
    const value = new DataView(this.bytes.buffer, this.bytes.byteOffset + this.offset, 8).getFloat64(0, !0);
    return this.offset += 8, value;
  }
  string() {
    const size = this.u32(), value = new TextDecoder().decode(this.bytes.slice(this.offset, this.offset + size));
    return this.offset += size, value;
  }
  doubles() {
    return Array.from({ length: this.u32() }, () => this.double());
  }
  strings() {
    return Array.from({ length: this.u32() }, () => this.string());
  }
}
function denseToEntries(dense) {
  const entries = [];
  return dense.forEach((row, rowIndex) => {
    row.forEach((value, columnIndex) => {
      value !== 0 && entries.push({ row: rowIndex, column: columnIndex, value });
    });
  }), entries;
}
function normalizeSparseMatrix(input, numRows, numColumns) {
  return input ? Array.isArray(input) ? denseToEntries(input) : input.dense ? denseToEntries(input.dense) : [...input.entries ?? []].filter((entry) => entry.value !== 0 && entry.row < numRows && entry.column < numColumns) : [];
}
function normalizeQuadraticProgram(input = {}) {
  const objectiveVector = input.objective_vector ?? input.objectiveVector ?? [], constraintLowerBounds = input.constraint_lower_bounds ?? input.constraintLowerBounds ?? [], constraintUpperBounds = input.constraint_upper_bounds ?? input.constraintUpperBounds ?? [], variableLowerBounds = input.variable_lower_bounds ?? input.variableLowerBounds ?? Array(objectiveVector.length).fill(-1 / 0), variableUpperBounds = input.variable_upper_bounds ?? input.variableUpperBounds ?? Array(objectiveVector.length).fill(1 / 0), numVariables = Math.max(objectiveVector.length, variableLowerBounds.length, variableUpperBounds.length), numConstraints = Math.max(constraintLowerBounds.length, constraintUpperBounds.length), constraintMatrix = input.constraint_matrix ?? input.constraintMatrix;
  return {
    problemName: input.problem_name ?? input.problemName ?? "",
    problem_name: input.problem_name ?? input.problemName ?? "",
    objectiveOffset: input.objective_offset ?? input.objectiveOffset ?? 0,
    objective_offset: input.objective_offset ?? input.objectiveOffset ?? 0,
    objectiveScalingFactor: input.objective_scaling_factor ?? input.objectiveScalingFactor ?? 1,
    objective_scaling_factor: input.objective_scaling_factor ?? input.objectiveScalingFactor ?? 1,
    objectiveVector: pad(objectiveVector, numVariables, 0),
    objective_vector: pad(objectiveVector, numVariables, 0),
    constraintLowerBounds: pad(constraintLowerBounds, numConstraints, -1 / 0),
    constraint_lower_bounds: pad(constraintLowerBounds, numConstraints, -1 / 0),
    constraintUpperBounds: pad(constraintUpperBounds, numConstraints, 1 / 0),
    constraint_upper_bounds: pad(constraintUpperBounds, numConstraints, 1 / 0),
    variableLowerBounds: pad(variableLowerBounds, numVariables, -1 / 0),
    variable_lower_bounds: pad(variableLowerBounds, numVariables, -1 / 0),
    variableUpperBounds: pad(variableUpperBounds, numVariables, 1 / 0),
    variable_upper_bounds: pad(variableUpperBounds, numVariables, 1 / 0),
    variableNames: input.variable_names ?? input.variableNames ?? [],
    variable_names: input.variable_names ?? input.variableNames ?? [],
    constraintNames: input.constraint_names ?? input.constraintNames ?? [],
    constraint_names: input.constraint_names ?? input.constraintNames ?? [],
    objectiveMatrixDiagonal: input.objective_matrix_diagonal ?? input.objectiveMatrixDiagonal ?? null,
    constraintMatrixEntries: normalizeSparseMatrix(constraintMatrix, numConstraints, numVariables),
    numVariables,
    numConstraints
  };
}
function pad(values, length, fill) {
  return [...values, ...Array(Math.max(0, length - values.length)).fill(fill)];
}
function encodeQuadraticProgram(input) {
  const qp = normalizeQuadraticProgram(input), writer = new BinaryWriter();
  writer.u32(qp.numVariables), writer.u32(qp.numConstraints), writer.string(qp.problemName), writer.double(qp.objectiveOffset), writer.double(qp.objectiveScalingFactor), writer.doubles(qp.objectiveVector), qp.objectiveMatrixDiagonal ? (writer.u8(1), writer.doubles(qp.objectiveMatrixDiagonal)) : writer.u8(0), writer.doubles(qp.constraintLowerBounds), writer.doubles(qp.constraintUpperBounds), writer.doubles(qp.variableLowerBounds), writer.doubles(qp.variableUpperBounds), writer.strings(qp.variableNames), writer.strings(qp.constraintNames), writer.u32(qp.constraintMatrixEntries.length);
  for (const entry of qp.constraintMatrixEntries)
    writer.u32(entry.row), writer.u32(entry.column), writer.double(entry.value);
  return writer.finish();
}
function decodeQuadraticProgram(bytes) {
  const reader = new BinaryReader(bytes), numVariables = reader.u32(), numConstraints = reader.u32(), problemName = reader.string(), objectiveOffset = reader.double(), objectiveScalingFactor = reader.double(), objectiveVector = reader.doubles(), objectiveMatrixDiagonal = reader.u8() ? reader.doubles() : null, constraintLowerBounds = reader.doubles(), constraintUpperBounds = reader.doubles(), variableLowerBounds = reader.doubles(), variableUpperBounds = reader.doubles(), variableNames = reader.strings(), constraintNames = reader.strings(), entries = Array.from({ length: reader.u32() }, () => ({
    row: reader.u32(),
    column: reader.u32(),
    value: reader.double()
  }));
  return new QuadraticProgram({
    problemName,
    objectiveOffset,
    objectiveScalingFactor,
    objectiveVector,
    objectiveMatrixDiagonal,
    constraintLowerBounds,
    constraintUpperBounds,
    variableLowerBounds,
    variableUpperBounds,
    variableNames,
    constraintNames,
    constraintMatrix: { numRows: numConstraints, numColumns: numVariables, entries }
  });
}
function encodeParams(params = {}) {
  const writer = new BinaryWriter(), terminationCriteria = params.terminationCriteria ?? params.termination_criteria, simple = terminationCriteria?.simpleOptimalityCriteria ?? terminationCriteria?.simple_optimality_criteria, iterationLimit = terminationCriteria?.iterationLimit ?? terminationCriteria?.iteration_limit;
  iterationLimit !== void 0 ? (writer.u8(1), writer.u32(iterationLimit)) : writer.u8(0);
  const terminationCheckFrequency = params.terminationCheckFrequency ?? params.termination_check_frequency;
  terminationCheckFrequency !== void 0 ? (writer.u8(1), writer.u32(terminationCheckFrequency)) : writer.u8(0);
  const epsOptimalRelative = simple?.epsOptimalRelative ?? simple?.eps_optimal_relative;
  epsOptimalRelative !== void 0 ? (writer.u8(1), writer.double(epsOptimalRelative)) : writer.u8(0);
  const epsOptimalAbsolute = simple?.epsOptimalAbsolute ?? simple?.eps_optimal_absolute;
  epsOptimalAbsolute !== void 0 ? (writer.u8(1), writer.double(epsOptimalAbsolute)) : writer.u8(0);
  const lInfRuizIterations = params.lInfRuizIterations ?? params.l_inf_ruiz_iterations;
  lInfRuizIterations !== void 0 ? (writer.u8(1), writer.u32(lInfRuizIterations)) : writer.u8(0);
  const l2NormRescaling = params.l2NormRescaling ?? params.l2_norm_rescaling;
  return l2NormRescaling !== void 0 ? (writer.u8(1), writer.u8(l2NormRescaling ? 1 : 0)) : writer.u8(0), writer.finish();
}
function encodeInitialSolution(solution) {
  const writer = new BinaryWriter();
  return solution ? (writer.u8(1), writer.doubles(solution.primal_solution ?? solution.primalSolution ?? []), writer.doubles(solution.dual_solution ?? solution.dualSolution ?? []), writer.finish()) : (writer.u8(0), writer.finish());
}
function decodeSolverResult(bytes) {
  const reader = new BinaryReader(bytes);
  if (reader.u8() === 0)
    throw new Error(reader.string() || "PDLP solve failed.");
  const primalSolution = reader.doubles(), dualSolution = reader.doubles(), reducedCosts = reader.doubles(), terminationReasonNumber = reader.u32(), iterationCount = reader.u32(), solveLog = {
    terminationReason: terminationReasonNames[terminationReasonNumber] ?? `TERMINATION_REASON_${terminationReasonNumber}`,
    termination_reason: terminationReasonNames[terminationReasonNumber] ?? `TERMINATION_REASON_${terminationReasonNumber}`,
    iterationCount,
    iteration_count: iterationCount
  };
  return {
    primalSolution,
    primal_solution: primalSolution,
    dualSolution,
    dual_solution: dualSolution,
    reducedCosts,
    reduced_costs: reducedCosts,
    solveLog,
    solve_log: solveLog
  };
}
async function pdlpBytes(operation, bytes, options = {}) {
  return shouldUseWorkerBridge() ? (await runPdlpWorker(operation, bytes, options)).bytes : (await initPdlp(), runWithBytes(bytes, (module, ptr, len) => readNativeBytes(module, async (lenPtr) => operation === "validate" ? await module.ccall(
    "pdlp_validate_quadratic_program",
    "number",
    ["number", "number", "number"],
    [ptr, len, lenPtr],
    { async: !0 }
  ) : operation === "fromMpModel" ? await module.ccall(
    "pdlp_qp_from_mpmodel_proto",
    "number",
    ["number", "number", "number", "number", "number"],
    [ptr, len, options.relaxIntegerVariables ? 1 : 0, options.includeNames ? 1 : 0, lenPtr],
    { async: !0 }
  ) : operation === "toMpModel" ? await module.ccall(
    "pdlp_qp_to_mpmodel_proto",
    "number",
    ["number", "number", "number"],
    [ptr, len, lenPtr],
    { async: !0 }
  ) : await module.ccall(
    "pdlp_primal_dual_hybrid_gradient",
    "number",
    ["number", "number", "number"],
    [ptr, len, lenPtr],
    { async: !0 }
  ))));
}
async function pdlpIsLinearProgram(bytes) {
  return shouldUseWorkerBridge() ? (await runPdlpWorker("isLinear", bytes)).value === 1 : (await initPdlp(), await runWithBytes(bytes, async (module, ptr, len) => await module.ccall(
    "pdlp_is_linear_program",
    "number",
    ["number", "number"],
    [ptr, len],
    { async: !0 }
  )) === 1);
}
class QuadraticProgram {
  constructor(input = {}) {
    __publicField(this, "problemName", "");
    __publicField(this, "problem_name", "");
    __publicField(this, "objectiveOffset", 0);
    __publicField(this, "objective_offset", 0);
    __publicField(this, "objectiveScalingFactor", 1);
    __publicField(this, "objective_scaling_factor", 1);
    __publicField(this, "objectiveVector", []);
    __publicField(this, "objective_vector", []);
    __publicField(this, "objectiveMatrixDiagonal", null);
    __publicField(this, "objective_matrix_diagonal", null);
    __publicField(this, "constraintMatrix", { entries: [] });
    __publicField(this, "constraint_matrix", this.constraintMatrix);
    __publicField(this, "constraintLowerBounds", []);
    __publicField(this, "constraint_lower_bounds", []);
    __publicField(this, "constraintUpperBounds", []);
    __publicField(this, "constraint_upper_bounds", []);
    __publicField(this, "variableLowerBounds", []);
    __publicField(this, "variable_lower_bounds", []);
    __publicField(this, "variableUpperBounds", []);
    __publicField(this, "variable_upper_bounds", []);
    __publicField(this, "variableNames", []);
    __publicField(this, "variable_names", []);
    __publicField(this, "constraintNames", []);
    __publicField(this, "constraint_names", []);
    this.assign(input);
  }
  resizeAndInitialize(numVariables, numConstraints) {
    this.objectiveVector = Array(numVariables).fill(0), this.objective_vector = this.objectiveVector, this.constraintLowerBounds = Array(numConstraints).fill(-1 / 0), this.constraint_lower_bounds = this.constraintLowerBounds, this.constraintUpperBounds = Array(numConstraints).fill(1 / 0), this.constraint_upper_bounds = this.constraintUpperBounds, this.variableLowerBounds = Array(numVariables).fill(-1 / 0), this.variable_lower_bounds = this.variableLowerBounds, this.variableUpperBounds = Array(numVariables).fill(1 / 0), this.variable_upper_bounds = this.variableUpperBounds, this.constraintMatrix = { numRows: numConstraints, numColumns: numVariables, entries: [] }, this.constraint_matrix = this.constraintMatrix;
  }
  resize_and_initialize(numVariables, numConstraints) {
    this.resizeAndInitialize(numVariables, numConstraints);
  }
  setObjectiveMatrixDiagonal(values) {
    this.objectiveMatrixDiagonal = [...values], this.objective_matrix_diagonal = this.objectiveMatrixDiagonal;
  }
  set_objective_matrix_diagonal(values) {
    this.setObjectiveMatrixDiagonal(values);
  }
  clearObjectiveMatrix() {
    this.objectiveMatrixDiagonal = null, this.objective_matrix_diagonal = null;
  }
  clear_objective_matrix() {
    this.clearObjectiveMatrix();
  }
  toBytes() {
    return encodeQuadraticProgram(this);
  }
  assign(input) {
    const qp = normalizeQuadraticProgram(input);
    this.problemName = qp.problemName, this.problem_name = qp.problemName, this.objectiveOffset = qp.objectiveOffset, this.objective_offset = qp.objectiveOffset, this.objectiveScalingFactor = qp.objectiveScalingFactor, this.objective_scaling_factor = qp.objectiveScalingFactor, this.objectiveVector = [...qp.objectiveVector], this.objective_vector = this.objectiveVector, this.objectiveMatrixDiagonal = qp.objectiveMatrixDiagonal ? [...qp.objectiveMatrixDiagonal] : null, this.objective_matrix_diagonal = this.objectiveMatrixDiagonal, this.constraintLowerBounds = [...qp.constraintLowerBounds], this.constraint_lower_bounds = this.constraintLowerBounds, this.constraintUpperBounds = [...qp.constraintUpperBounds], this.constraint_upper_bounds = this.constraintUpperBounds, this.variableLowerBounds = [...qp.variableLowerBounds], this.variable_lower_bounds = this.variableLowerBounds, this.variableUpperBounds = [...qp.variableUpperBounds], this.variable_upper_bounds = this.variableUpperBounds, this.variableNames = [...qp.variableNames], this.variable_names = this.variableNames, this.constraintNames = [...qp.constraintNames], this.constraint_names = this.constraintNames, this.constraintMatrix = {
      numRows: qp.numConstraints,
      numColumns: qp.numVariables,
      entries: [...qp.constraintMatrixEntries]
    }, this.constraint_matrix = this.constraintMatrix;
  }
}
class PrimalAndDualSolution {
  constructor(input = {}) {
    __publicField(this, "primalSolution", []);
    __publicField(this, "primal_solution", []);
    __publicField(this, "dualSolution", []);
    __publicField(this, "dual_solution", []);
    this.primalSolution = [...input.primalSolution ?? input.primal_solution ?? []], this.primal_solution = this.primalSolution, this.dualSolution = [...input.dualSolution ?? input.dual_solution ?? []], this.dual_solution = this.dualSolution;
  }
}
const Pdlp = {
  QuadraticProgram,
  PrimalAndDualSolution,
  setWorkerBridgeEnabled(enabled) {
    setWorkerBridgeEnabled(enabled);
  },
  isWorkerBridgeEnabled() {
    return isWorkerBridgeEnabled();
  },
  async validateQuadraticProgramDimensions(qp) {
    const message = new TextDecoder().decode(await pdlpBytes("validate", encodeQuadraticProgram(qp)));
    if (message) throw new Error(message);
  },
  async validate_quadratic_program_dimensions(qp) {
    return this.validateQuadraticProgramDimensions(qp);
  },
  async isLinearProgram(qp) {
    return pdlpIsLinearProgram(encodeQuadraticProgram(qp));
  },
  async is_linear_program(qp) {
    return this.isLinearProgram(qp);
  },
  async qpFromMpModelProto(proto, options = {}) {
    const bytes = await pdlpBytes("fromMpModel", proto, options);
    if (!bytes.length) throw new Error("PDLP could not convert MPModelProto to QuadraticProgram.");
    return decodeQuadraticProgram(bytes);
  },
  async qp_from_mpmodel_proto(proto, relaxIntegerVariables = !1, includeNames = !1) {
    return this.qpFromMpModelProto(proto, { relaxIntegerVariables, includeNames });
  },
  async qpToMpModelProto(qp) {
    const bytes = await pdlpBytes("toMpModel", encodeQuadraticProgram(qp));
    if (!bytes.length) throw new Error("PDLP could not convert QuadraticProgram to MPModelProto.");
    return bytes;
  },
  async qp_to_mpmodel_proto(qp) {
    return this.qpToMpModelProto(qp);
  },
  async primalDualHybridGradient(qp, params = {}, initialSolution) {
    const bytes = concat([encodeQuadraticProgram(qp), encodeParams(params), encodeInitialSolution(initialSolution)]), resultBytes = await pdlpBytes("solve", bytes);
    if (!resultBytes.length) throw new Error("PDLP solve failed.");
    return decodeSolverResult(resultBytes);
  },
  async primal_dual_hybrid_gradient(qp, params = {}, initialSolution) {
    return this.primalDualHybridGradient(qp, params, initialSolution);
  }
};
function concat(parts) {
  const size = parts.reduce((sum, part) => sum + part.length, 0), output = new Uint8Array(size);
  let offset = 0;
  for (const part of parts)
    output.set(part, offset), offset += part.length;
  return output;
}
export {
  Pdlp,
  PrimalAndDualSolution,
  QuadraticProgram,
  initPdlp
};
