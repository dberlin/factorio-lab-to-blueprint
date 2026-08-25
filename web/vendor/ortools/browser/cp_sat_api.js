import { loadRuntime } from "./runtime_loader.js";
import {
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled,
  isWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
import * as protobufModule from "protobufjs";
import {
  CpSolverStatus,
  DecisionStrategyProto_DomainReductionStrategy,
  DecisionStrategyProto_VariableSelectionStrategy
} from "./generated/cp_model.js";
const isBrowserMainThread = typeof window < "u" && typeof document < "u";
let activeWorkerSolveId = null;
const SOLUTION_CALLBACK_FLAG = 1, BEST_BOUND_CALLBACK_FLAG = 2, LOG_CALLBACK_FLAG = 4, SOLUTION_CALLBACK_EVENT = 1, BEST_BOUND_CALLBACK_EVENT = 2, LOG_CALLBACK_EVENT = 3;
function callbackFlags(callbacks) {
  let flags = 0;
  return callbacks?.onSolution && (flags |= SOLUTION_CALLBACK_FLAG), callbacks?.onBestBound && (flags |= BEST_BOUND_CALLBACK_FLAG), callbacks?.onLog && (flags |= LOG_CALLBACK_FLAG), flags;
}
let modulePromise = null;
function loadModule() {
  if (shouldUseWorkerBridge())
    throw new Error("Wasm should not be loaded on main thread when Worker Bridge is enabled");
  return modulePromise ?? (modulePromise = loadRuntime()), modulePromise;
}
let schemaPromise = null;
function getSchemas() {
  return schemaPromise || (schemaPromise = (async () => {
    if (shouldUseWorkerBridge()) {
      const response = await postWorkerRequest({
        type: "getSchemas",
        id: nextWorkerBridgeRequestId(),
        schema: "cp_sat"
      });
      if (response.schema !== "cp_sat")
        throw new Error("Worker returned the wrong schema payload for CP-SAT.");
      return response.schemas;
    }
    const Module = await loadModule();
    return {
      cp_model: Module.ccall("get_cp_model_schema", "string", [], []),
      sat_parameters: Module.ccall("get_sat_parameters_schema", "string", [], [])
    };
  })()), schemaPromise;
}
let protobufRootPromise = null, cpModelTypePromise = null, cpSolverResponseTypePromise = null, satParametersTypePromise = null;
async function resolveProtobufRoot(feature) {
  protobufRootPromise || (protobufRootPromise = (async () => {
    const schemas = await getSchemas();
    return protobufModule.parse(schemas.cp_model).root;
  })());
  try {
    return await protobufRootPromise;
  } catch (error) {
    throw protobufRootPromise = null, error;
  }
}
async function resolveCpModelType() {
  cpModelTypePromise || (cpModelTypePromise = (async () => {
    const cpModelType = (await resolveProtobufRoot("createModel")).lookupType("operations_research.sat.CpModelProto");
    if (!cpModelType)
      throw new Error("CpSat.createModel: cp_model schema did not expose operations_research.sat.CpModelProto.");
    return cpModelType;
  })());
  try {
    return await cpModelTypePromise;
  } catch (error) {
    throw cpModelTypePromise = null, error;
  }
}
async function resolveCpSolverResponseType() {
  cpSolverResponseTypePromise || (cpSolverResponseTypePromise = (async () => {
    const solverType = (await resolveProtobufRoot("solve")).lookupType("operations_research.sat.CpSolverResponse");
    if (!solverType)
      throw new Error("CpSat.solve: cp_model schema did not expose operations_research.sat.CpSolverResponse.");
    return solverType;
  })());
  try {
    return await cpSolverResponseTypePromise;
  } catch (error) {
    throw cpSolverResponseTypePromise = null, error;
  }
}
async function resolveSatParametersType() {
  satParametersTypePromise || (satParametersTypePromise = (async () => {
    const schemas = await getSchemas(), paramsType = protobufModule.parse(schemas.sat_parameters).root.lookupType("operations_research.sat.SatParameters");
    if (!paramsType)
      throw new Error("CpSat.solve: sat_parameters schema did not expose operations_research.sat.SatParameters.");
    return paramsType;
  })());
  try {
    return await satParametersTypePromise;
  } catch (error) {
    throw satParametersTypePromise = null, error;
  }
}
function normalizeSatParameters(params) {
  if (params.numSearchWorkers === void 0)
    return params;
  const { numSearchWorkers, ...normalizedParams } = params;
  return normalizedParams.numWorkers !== void 0 ? normalizedParams : {
    ...normalizedParams,
    numWorkers: numSearchWorkers
  };
}
async function encodeSatParameters(params) {
  const paramsType = await resolveSatParametersType(), normalizedParams = normalizeSatParameters(params), validationError = paramsType.verify(normalizedParams);
  if (validationError)
    throw new Error(`CpSat.solve: ${validationError}`);
  const message = paramsType.create(normalizedParams);
  return paramsType.encode(message).finish();
}
async function resolveParamsBytes(params) {
  return params ? params instanceof Uint8Array ? params : encodeSatParameters(params) : null;
}
async function decodeSolverResponse(bytes) {
  const solverType = await resolveCpSolverResponseType();
  return toCpSolverResponse(solverType, bytes);
}
function toCpSolverResponse(solverType, bytes) {
  const decoded = solverType.decode(bytes);
  return solverType.toObject(decoded, {
    enums: String,
    longs: Number,
    defaults: !0,
    arrays: !0,
    objects: !0
  });
}
function dispatchSolveCallback(callbacks, solverType, event) {
  if (event.eventType === "solution") {
    const bytes = new Uint8Array(event.bytes);
    callbacks?.onSolution?.(toCpSolverResponse(solverType, bytes), bytes);
  } else event.eventType === "bestBound" ? callbacks?.onBestBound?.(event.bound) : event.eventType === "log" && callbacks?.onLog?.(event.message);
}
function normalizeCpModelForProtobuf(model) {
  return {
    ...model,
    constraints: model.constraints?.map((constraint) => {
      if (!constraint.noOverlap2d)
        return constraint;
      const normalized = {
        ...constraint,
        noOverlap_2d: constraint.noOverlap2d
      };
      return delete normalized.noOverlap2d, normalized;
    })
  };
}
async function createModel(model) {
  const type = await resolveCpModelType(), protobufModel = normalizeCpModelForProtobuf(model), validationError = type.verify(protobufModel);
  if (validationError)
    throw new Error(`CpSat.createModel: ${validationError}`);
  const message = type.create(protobufModel);
  return type.encode(message).finish();
}
async function modelStats(model) {
  const type = await resolveCpModelType(), decoded = type.decode(model), object = type.toObject(decoded, {
    enums: String,
    longs: Number,
    defaults: !0,
    arrays: !0,
    objects: !0
  });
  return JSON.stringify({
    name: object.name ?? "",
    variables: object.variables?.length ?? 0,
    constraints: object.constraints?.length ?? 0,
    hasObjective: object.objective !== void 0 || object.floatingPointObjective !== void 0
  });
}
const readUint32LE = (buffer, ptr) => new DataView(buffer, ptr, 4).getUint32(0, !0);
function readUint32FromBytes(bytes, offset) {
  return new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getUint32(0, !0);
}
function parseCallbackEnvelope(bytes) {
  let offset = 0;
  const events = [], eventCount = readUint32FromBytes(bytes, offset);
  offset += 4;
  for (let i = 0; i < eventCount; i++) {
    const eventType = bytes[offset++], payloadLength = readUint32FromBytes(bytes, offset);
    offset += 4;
    const payload = bytes.slice(offset, offset + payloadLength);
    offset += payloadLength, eventType === SOLUTION_CALLBACK_EVENT ? events.push({ eventType: "solution", bytes: payload }) : eventType === BEST_BOUND_CALLBACK_EVENT ? events.push({
      eventType: "bestBound",
      bound: new DataView(payload.buffer, payload.byteOffset, payload.byteLength).getFloat64(0, !0)
    }) : eventType === LOG_CALLBACK_EVENT && events.push({ eventType: "log", message: new TextDecoder().decode(payload) });
  }
  const responseLength = readUint32FromBytes(bytes, offset);
  return offset += 4, { events, responseBytes: bytes.slice(offset, offset + responseLength) };
}
function copyBytesToHeap(Module, bytes) {
  if (!bytes || !bytes.length)
    return 0;
  const ptr = Module._malloc(bytes.length);
  return Module.HEAPU8.set(bytes, ptr), ptr;
}
async function solveRawViaWorker(modelBytes, paramsBytes = null, callbacks, solverType) {
  const id = nextWorkerBridgeRequestId();
  activeWorkerSolveId = id;
  try {
    const response = await postWorkerRequest(
      {
        type: "solve",
        id,
        modelBytes,
        paramsBytes: paramsBytes ?? void 0,
        callbackFlags: callbackFlags(callbacks)
      },
      (event) => {
        event.type === "solveCallback" && solverType && dispatchSolveCallback(callbacks, solverType, event);
      }
    );
    return new Uint8Array(response.bytes);
  } finally {
    activeWorkerSolveId === id && (activeWorkerSolveId = null);
  }
}
async function validateViaWorker(modelBytes) {
  const id = nextWorkerBridgeRequestId(), response = await postWorkerRequest({
    type: "validate",
    id,
    modelBytes
  });
  return { ok: response.ok, message: response.message };
}
async function solveRawDirect(modelBytes, paramsBytes = null, callbacks, solverType) {
  const Module = await loadModule(), lenPtr = Module._malloc(4), modelPtr = copyBytesToHeap(Module, modelBytes), paramsPtr = copyBytesToHeap(Module, paramsBytes);
  let responsePtr = 0;
  const flags = callbackFlags(callbacks), useCallbackEnvelope = flags !== 0 && solverType !== void 0;
  try {
    useCallbackEnvelope ? responsePtr = await Module.ccall(
      "solve_model_with_callback_events",
      "number",
      ["number", "number", "number", "number", "number", "number"],
      [
        modelPtr,
        modelBytes.length,
        paramsPtr,
        paramsBytes ? paramsBytes.length : 0,
        flags,
        lenPtr
      ],
      { async: !0 }
    ) : responsePtr = await Module.ccall(
      "solve_model",
      "number",
      ["number", "number", "number", "number", "number"],
      [
        modelPtr,
        modelBytes.length,
        paramsPtr,
        paramsBytes ? paramsBytes.length : 0,
        lenPtr
      ],
      { async: !0 }
    );
  } finally {
    modelPtr && Module._free(modelPtr), paramsPtr && Module._free(paramsPtr);
  }
  const len = readUint32LE(Module.HEAPU8.buffer, lenPtr);
  Module._free(lenPtr);
  let bytes = new Uint8Array();
  if (responsePtr && len ? (bytes = Module.HEAPU8.slice(responsePtr, responsePtr + len), Module._free_buffer(responsePtr)) : responsePtr && Module._free_buffer(responsePtr), useCallbackEnvelope && solverType) {
    const { events, responseBytes } = parseCallbackEnvelope(bytes);
    for (const event of events)
      dispatchSolveCallback(callbacks, solverType, event);
    return responseBytes;
  }
  return new Uint8Array(bytes);
}
async function solveRaw(modelBytes, paramsBytes = null, callbacks, solverType) {
  return shouldUseWorkerBridge() ? solveRawViaWorker(modelBytes, paramsBytes, callbacks, solverType) : solveRawDirect(modelBytes, paramsBytes, callbacks, solverType);
}
async function solve(modelBytes, params = null, callbacks) {
  const paramsBytes = await resolveParamsBytes(params), solverType = callbacks && callbackFlags(callbacks) ? await resolveCpSolverResponseType() : void 0, started = typeof performance < "u" ? performance.now() : Date.now(), bytes = await solveRaw(modelBytes, paramsBytes, callbacks, solverType), elapsedSeconds = ((typeof performance < "u" ? performance.now() : Date.now()) - started) / 1e3;
  let response = null;
  return bytes.length > 0 && (response = solverType ? toCpSolverResponse(solverType, bytes) : await decodeSolverResponse(bytes), (response.wallTime ?? 0) <= 0 && (response.wallTime = Math.max(elapsedSeconds, Number.EPSILON))), { bytes, response };
}
async function validateDirect(model) {
  const Module = await loadModule(), lenPtr = Module._malloc(4), modelPtr = copyBytesToHeap(Module, model);
  let msgPtr = 0;
  try {
    msgPtr = await Module.ccall(
      "validate_model",
      "number",
      ["number", "number", "number"],
      [modelPtr, model.length, lenPtr],
      { async: !0 }
    );
  } finally {
    modelPtr && Module._free(modelPtr);
  }
  const len = readUint32LE(Module.HEAPU8.buffer, lenPtr);
  if (Module._free(lenPtr), !msgPtr || len === 0)
    return msgPtr && Module._free_buffer(msgPtr), { ok: !0, message: "" };
  const messageBytes = Module.HEAPU8.slice(msgPtr, msgPtr + len);
  return Module._free_buffer(msgPtr), { ok: !1, message: new TextDecoder().decode(messageBytes) };
}
async function cancelSolve() {
  shouldUseWorkerBridge() ? activeWorkerSolveId !== null && (await postWorkerRequest({
    type: "cancel_solve",
    id: nextWorkerBridgeRequestId(),
    targetId: activeWorkerSolveId
  }), activeWorkerSolveId = null) : (await loadModule()).ccall("interrupt_solve", "void", [], []);
}
const CpSat = {
  solve: (model, params = null, callbacks) => solve(model, params, callbacks),
  solveRaw: (model, params = null) => solveRaw(model, params),
  validate: (model) => shouldUseWorkerBridge() ? validateViaWorker(model) : validateDirect(model),
  modelStats,
  getSchemas,
  createModel,
  loadModule,
  cancelSolve,
  setWorkerBridgeEnabled: (enabled) => setWorkerBridgeEnabled(enabled),
  isWorkerBridgeEnabled: () => isWorkerBridgeEnabled()
};
isBrowserMainThread && (window.CpSat = CpSat);
var stdin_default = CpSat;
export {
  CpSat,
  CpSolverStatus,
  DecisionStrategyProto_DomainReductionStrategy,
  DecisionStrategyProto_VariableSelectionStrategy,
  stdin_default as default
};
