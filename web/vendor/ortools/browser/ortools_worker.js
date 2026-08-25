import {
  loadGraphRuntime,
  loadMathOptRuntime,
  loadMPSolverRuntime,
  loadPdlpRuntime,
  loadRuntime,
  loadSetCoverRuntime
} from "./runtime_loader.js";
import { solveRoutingInWorker } from "./worker_routing.js";
Object.assign(globalThis, { __ORTOOLS_WASM_BRIDGE_WORKER: !0 });
const workerScope = self, SOLUTION_CALLBACK_EVENT = 1, BEST_BOUND_CALLBACK_EVENT = 2, LOG_CALLBACK_EVENT = 3;
let moduleInstance = null;
workerScope.postMessage({ type: "ready" });
async function loadCpSatModule() {
  return moduleInstance ?? (moduleInstance = await loadRuntime()), moduleInstance;
}
const readUint32LE = (buffer, ptr) => new DataView(buffer, ptr, 4).getUint32(0, !0);
function readUint32FromBytes(bytes, offset) {
  return new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getUint32(0, !0);
}
function postCallbackEnvelopeEvents(id, bytes) {
  let offset = 0;
  const eventCount = readUint32FromBytes(bytes, offset);
  offset += 4;
  for (let i = 0; i < eventCount; i++) {
    const eventType = bytes[offset++], payloadLength = readUint32FromBytes(bytes, offset);
    offset += 4;
    const payload = bytes.slice(offset, offset + payloadLength);
    offset += payloadLength, eventType === SOLUTION_CALLBACK_EVENT ? workerScope.postMessage({
      type: "solveCallback",
      id,
      eventType: "solution",
      bytes: payload
    }) : eventType === BEST_BOUND_CALLBACK_EVENT ? workerScope.postMessage({
      type: "solveCallback",
      id,
      eventType: "bestBound",
      bound: new DataView(payload.buffer, payload.byteOffset, payload.byteLength).getFloat64(0, !0)
    }) : eventType === LOG_CALLBACK_EVENT && workerScope.postMessage({
      type: "solveCallback",
      id,
      eventType: "log",
      message: new TextDecoder().decode(payload)
    });
  }
  const responseLength = readUint32FromBytes(bytes, offset);
  return offset += 4, bytes.slice(offset, offset + responseLength);
}
const copyBytesToHeap = (module, bytes) => {
  if (!bytes?.length)
    return 0;
  const ptr = module._malloc(bytes.length);
  return module.HEAPU8.set(bytes, ptr), ptr;
};
function copyFloat64ToHeap(module, values) {
  if (!values.length) return 0;
  const ptr = module._malloc(values.length * Float64Array.BYTES_PER_ELEMENT);
  return new Float64Array(module.HEAPU8.buffer, ptr, values.length).set(values), ptr;
}
function flattenWeights(weights, itemCount) {
  const flattened = [];
  for (const dimension of weights) {
    if (dimension.length !== itemCount)
      throw new Error("KnapsackSolver: each weight dimension must match profits length.");
    flattened.push(...dimension);
  }
  return flattened;
}
async function solveKnapsackInWorker(message) {
  const module = await loadMPSolverRuntime(), profitsPtr = copyFloat64ToHeap(module, message.profits), weightsPtr = copyFloat64ToHeap(module, flattenWeights(message.weights, message.profits.length)), capacitiesPtr = copyFloat64ToHeap(module, message.capacities), namePtr = module.allocateUTF8(message.name);
  try {
    return await module.ccall(
      "knapsack_solve_serialized",
      "string",
      ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
      [
        message.solverType,
        namePtr,
        message.useReduction ? 1 : 0,
        message.timeLimitSeconds,
        profitsPtr,
        message.profits.length,
        weightsPtr,
        message.weights.length,
        capacitiesPtr
      ],
      { async: !0 }
    );
  } finally {
    profitsPtr && module._free(profitsPtr), weightsPtr && module._free(weightsPtr), capacitiesPtr && module._free(capacitiesPtr), module._free(namePtr);
  }
}
async function solveGraphInWorker(message) {
  const module = await loadGraphRuntime();
  if (message.algorithm === "maxFlow") {
    const tailsPtr = copyFloat64ToHeap(module, message.tails), headsPtr = copyFloat64ToHeap(module, message.heads), capacitiesPtr = copyFloat64ToHeap(module, message.capacities);
    try {
      return await module.ccall(
        "graph_max_flow_solve_serialized",
        "string",
        ["number", "number", "number", "number", "number", "number"],
        [tailsPtr, headsPtr, capacitiesPtr, message.tails.length, message.source, message.sink],
        { async: !0 }
      );
    } finally {
      tailsPtr && module._free(tailsPtr), headsPtr && module._free(headsPtr), capacitiesPtr && module._free(capacitiesPtr);
    }
  }
  if (message.algorithm === "minCostFlow") {
    const tailsPtr = copyFloat64ToHeap(module, message.tails), headsPtr = copyFloat64ToHeap(module, message.heads), capacitiesPtr = copyFloat64ToHeap(module, message.capacities), unitCostsPtr = copyFloat64ToHeap(module, message.unitCosts), suppliesPtr = copyFloat64ToHeap(module, message.supplies);
    try {
      return await module.ccall(
        "graph_min_cost_flow_solve_serialized",
        "string",
        ["number", "number", "number", "number", "number", "number", "number", "number"],
        [
          tailsPtr,
          headsPtr,
          capacitiesPtr,
          unitCostsPtr,
          message.tails.length,
          suppliesPtr,
          message.supplies.length,
          message.solveMaxFlowWithMinCost ? 1 : 0
        ],
        { async: !0 }
      );
    } finally {
      tailsPtr && module._free(tailsPtr), headsPtr && module._free(headsPtr), capacitiesPtr && module._free(capacitiesPtr), unitCostsPtr && module._free(unitCostsPtr), suppliesPtr && module._free(suppliesPtr);
    }
  }
  const leftNodesPtr = copyFloat64ToHeap(module, message.leftNodes), rightNodesPtr = copyFloat64ToHeap(module, message.rightNodes), costsPtr = copyFloat64ToHeap(module, message.costs);
  try {
    return await module.ccall(
      "graph_linear_sum_assignment_solve_serialized",
      "string",
      ["number", "number", "number", "number"],
      [leftNodesPtr, rightNodesPtr, costsPtr, message.leftNodes.length],
      { async: !0 }
    );
  } finally {
    leftNodesPtr && module._free(leftNodesPtr), rightNodesPtr && module._free(rightNodesPtr), costsPtr && module._free(costsPtr);
  }
}
function setCoverOperationCode(operation) {
  switch (operation) {
    case "trivial":
      return 0;
    case "greedy":
      return 1;
    case "elementDegree":
      return 2;
    case "lazyElementDegree":
      return 3;
    case "random":
      return 4;
    case "steepest":
      return 5;
    case "guidedLocal":
      return 6;
    case "guidedTabu":
      return 7;
  }
}
async function solveSetCoverInWorker(message) {
  const module = await loadSetCoverRuntime(), costsPtr = copyFloat64ToHeap(module, message.costs), startsPtr = copyFloat64ToHeap(module, message.starts), elementsPtr = copyFloat64ToHeap(module, message.elements), selectedPtr = copyFloat64ToHeap(module, message.selected.map((value) => value ? 1 : 0)), focusPtr = message.focus ? copyFloat64ToHeap(module, message.focus.map((value) => value ? 1 : 0)) : 0;
  try {
    return await module.ccall(
      "set_cover_next_solution_serialized",
      "string",
      ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
      [
        costsPtr,
        startsPtr,
        elementsPtr,
        message.costs.length,
        message.elements.length,
        selectedPtr,
        focusPtr,
        setCoverOperationCode(message.operation),
        message.maxIterations
      ],
      { async: !0 }
    );
  } finally {
    costsPtr && module._free(costsPtr), startsPtr && module._free(startsPtr), elementsPtr && module._free(elementsPtr), selectedPtr && module._free(selectedPtr), focusPtr && module._free(focusPtr);
  }
}
async function solveModel(modelBytes, paramsBytes, requestId = 0, callbackFlags = 0) {
  const module = await loadCpSatModule(), lenPtr = module._malloc(4), modelPtr = copyBytesToHeap(module, modelBytes), paramsPtr = copyBytesToHeap(module, paramsBytes ?? null);
  let responsePtr = 0;
  try {
    callbackFlags ? responsePtr = await module.ccall(
      "solve_model_with_callback_events",
      "number",
      ["number", "number", "number", "number", "number", "number"],
      [
        modelPtr,
        modelBytes.length,
        paramsPtr,
        paramsBytes ? paramsBytes.length : 0,
        callbackFlags,
        lenPtr
      ],
      { async: !0 }
    ) : responsePtr = await module.ccall(
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
    modelPtr && module._free(modelPtr), paramsPtr && module._free(paramsPtr);
  }
  const len = readUint32LE(module.HEAPU8.buffer, lenPtr);
  if (module._free(lenPtr), !responsePtr || len === 0)
    return responsePtr && module._free_buffer(responsePtr), new Uint8Array();
  const bytes = module.HEAPU8.slice(responsePtr, responsePtr + len);
  return module._free_buffer(responsePtr), callbackFlags ? postCallbackEnvelopeEvents(requestId, bytes) : bytes;
}
async function validateModel(modelBytes) {
  const module = await loadCpSatModule(), lenPtr = module._malloc(4), modelPtr = copyBytesToHeap(module, modelBytes);
  let msgPtr = 0;
  try {
    msgPtr = await module.ccall(
      "validate_model",
      "number",
      ["number", "number", "number"],
      [modelPtr, modelBytes.length, lenPtr],
      { async: !0 }
    );
  } finally {
    modelPtr && module._free(modelPtr);
  }
  const len = readUint32LE(module.HEAPU8.buffer, lenPtr);
  if (module._free(lenPtr), !msgPtr || len === 0)
    return msgPtr && module._free_buffer(msgPtr), { ok: !0, message: "" };
  const messageBytes = module.HEAPU8.slice(msgPtr, msgPtr + len);
  return module._free_buffer(msgPtr), { ok: !1, message: new TextDecoder().decode(messageBytes) };
}
function copyResponseBytes(module, responsePtr, lenPtr) {
  const responseLen = readUint32LE(module.HEAPU8.buffer, lenPtr);
  return responsePtr && responseLen ? module.HEAPU8.slice(responsePtr, responsePtr + responseLen) : new Uint8Array();
}
function freeResponseBuffer(module, responsePtr) {
  responsePtr && module.ccall("free_buffer", void 0, ["number"], [responsePtr]);
}
async function callSerializedBytesFunction(module, requestBytes, call) {
  const lenPtr = module._malloc(4), requestPtr = copyBytesToHeap(module, requestBytes);
  let responsePtr = 0;
  try {
    return responsePtr = await call(requestPtr, requestBytes.length, lenPtr), copyResponseBytes(module, responsePtr, lenPtr);
  } finally {
    freeResponseBuffer(module, responsePtr), requestPtr && module._free(requestPtr), module._free(lenPtr);
  }
}
async function withHeapBytes(module, bytes, callback) {
  const ptr = copyBytesToHeap(module, bytes);
  try {
    return await callback(ptr, bytes?.length ?? 0);
  } finally {
    ptr && module._free(ptr);
  }
}
async function solveMPSolverInWorker(message) {
  const module = await loadMPSolverRuntime(), numThreads = typeof message.numThreads == "number" && Number.isInteger(message.numThreads) && message.numThreads > 1 ? message.numThreads : void 0;
  return numThreads === void 0 ? callSerializedBytesFunction(module, message.requestBytes, async (requestPtr, requestLength, lenPtr) => await module.ccall(
    "mp_solver_solve_model_request",
    "number",
    ["number", "number", "number"],
    [requestPtr, requestLength, lenPtr],
    { async: !0 }
  )) : callSerializedBytesFunction(module, message.requestBytes, async (requestPtr, requestLength, lenPtr) => await module.ccall(
    "mp_solver_solve_model_request_with_threads",
    "number",
    ["number", "number", "number", "number"],
    [requestPtr, requestLength, numThreads, lenPtr],
    { async: !0 }
  ));
}
async function solveMathOptInWorker(message) {
  const module = await loadMathOptRuntime();
  return callSerializedBytesFunction(module, message.requestBytes, async (requestPtr, requestLength, lenPtr) => await module.ccall(
    "mathopt_solve_request",
    "number",
    ["number", "number", "number", "number", "number"],
    [
      requestPtr,
      requestLength,
      message.useInterrupter ? 1 : 0,
      message.interruptAtStart ? 1 : 0,
      lenPtr
    ],
    { async: !0 }
  ));
}
async function createMathOptIncrementalInWorker(message) {
  const module = await loadMathOptRuntime();
  return callSerializedBytesFunction(module, message.requestBytes, async (requestPtr, requestLength, lenPtr) => await module.ccall(
    "mathopt_incremental_create",
    "number",
    ["number", "number", "number"],
    [requestPtr, requestLength, lenPtr],
    { async: !0 }
  ));
}
async function solveMathOptIncrementalInWorker(message) {
  const module = await loadMathOptRuntime();
  return withHeapBytes(module, message.updateBytes ?? null, async (updatePtr, updateLength) => callSerializedBytesFunction(module, message.requestBytes, async (requestPtr, requestLength, lenPtr) => await module.ccall(
    "mathopt_incremental_solve",
    "number",
    ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
    [
      message.handle,
      requestPtr,
      requestLength,
      updatePtr,
      updateLength,
      message.updateBytes ? 1 : 0,
      message.useInterrupter ? 1 : 0,
      message.interruptAtStart ? 1 : 0,
      lenPtr
    ],
    { async: !0 }
  )));
}
async function deleteMathOptIncrementalInWorker(message) {
  await (await loadMathOptRuntime()).ccall("mathopt_incremental_delete", void 0, ["number"], [message.handle], { async: !0 });
}
async function solvePdlpInWorker(message) {
  const module = await loadPdlpRuntime();
  if (message.operation === "isLinear") {
    const value = await withHeapBytes(module, message.bytes, async (requestPtr, requestLength) => await module.ccall(
      "pdlp_is_linear_program",
      "number",
      ["number", "number"],
      [requestPtr, requestLength],
      { async: !0 }
    ));
    return { bytes: new Uint8Array(), value };
  }
  return { bytes: await callSerializedBytesFunction(module, message.bytes, async (requestPtr, requestLength, lenPtr) => message.operation === "validate" ? await module.ccall(
    "pdlp_validate_quadratic_program",
    "number",
    ["number", "number", "number"],
    [requestPtr, requestLength, lenPtr],
    { async: !0 }
  ) : message.operation === "fromMpModel" ? await module.ccall(
    "pdlp_qp_from_mpmodel_proto",
    "number",
    ["number", "number", "number", "number", "number"],
    [
      requestPtr,
      requestLength,
      message.relaxIntegerVariables ? 1 : 0,
      message.includeNames ? 1 : 0,
      lenPtr
    ],
    { async: !0 }
  ) : message.operation === "toMpModel" ? await module.ccall(
    "pdlp_qp_to_mpmodel_proto",
    "number",
    ["number", "number", "number"],
    [requestPtr, requestLength, lenPtr],
    { async: !0 }
  ) : await module.ccall(
    "pdlp_primal_dual_hybrid_gradient",
    "number",
    ["number", "number", "number"],
    [requestPtr, requestLength, lenPtr],
    { async: !0 }
  )) };
}
const handlers = {
  validate: async (message) => {
    const validation = await validateModel(message.modelBytes);
    return {
      type: "validateResult",
      id: message.id,
      ok: validation.ok,
      message: validation.message
    };
  },
  solve: async (message) => {
    const bytes = await solveModel(message.modelBytes, message.paramsBytes, message.id, message.callbackFlags ?? 0);
    return {
      type: "solveResult",
      id: message.id,
      bytes
    };
  },
  routingSolve: async (message) => {
    const result = await solveRoutingInWorker(message);
    return {
      type: "routingSolveResult",
      id: message.id,
      result
    };
  },
  mpSolverSolve: async (message) => ({
    type: "mpSolverSolveResult",
    id: message.id,
    bytes: await solveMPSolverInWorker(message)
  }),
  knapsackSolve: async (message) => ({
    type: "knapsackSolveResult",
    id: message.id,
    result: await solveKnapsackInWorker(message)
  }),
  graphSolve: async (message) => ({
    type: "graphSolveResult",
    id: message.id,
    result: await solveGraphInWorker(message)
  }),
  setCover: async (message) => ({
    type: "setCoverResult",
    id: message.id,
    result: await solveSetCoverInWorker(message)
  }),
  mathOptInit: async (message) => (await loadMathOptRuntime(), {
    type: "mathOptInitResult",
    id: message.id
  }),
  mathOptSolve: async (message) => ({
    type: "mathOptSolveResult",
    id: message.id,
    bytes: await solveMathOptInWorker(message)
  }),
  mathOptIncrementalCreate: async (message) => ({
    type: "mathOptIncrementalResult",
    id: message.id,
    bytes: await createMathOptIncrementalInWorker(message)
  }),
  mathOptIncrementalSolve: async (message) => ({
    type: "mathOptIncrementalResult",
    id: message.id,
    bytes: await solveMathOptIncrementalInWorker(message)
  }),
  mathOptIncrementalDelete: async (message) => (await deleteMathOptIncrementalInWorker(message), {
    type: "mathOptIncrementalDeleted",
    id: message.id
  }),
  pdlp: async (message) => {
    const result = await solvePdlpInWorker(message);
    return {
      type: "pdlpResult",
      id: message.id,
      bytes: result.bytes,
      value: result.value
    };
  },
  getSchemas: async (message) => {
    if (message.schema === "cp_sat") {
      const module = await loadCpSatModule();
      return {
        type: "schemaResult",
        id: message.id,
        schema: "cp_sat",
        schemas: {
          cp_model: module.ccall("get_cp_model_schema", "string", [], []),
          sat_parameters: module.ccall("get_sat_parameters_schema", "string", [], [])
        }
      };
    }
    if (message.schema === "mp_solver") {
      const mpModule = await loadMPSolverRuntime();
      return {
        type: "schemaResult",
        id: message.id,
        schema: "mp_solver",
        schemas: {
          linear_solver: mpModule.ccall("get_linear_solver_schema", "string", [], []),
          optional_boolean: mpModule.ccall("get_optional_boolean_schema", "string", [], [])
        }
      };
    }
    throw new Error("Unsupported schema request.");
  },
  cancel_solve: async (message) => ((await loadCpSatModule()).ccall("interrupt_solve", "void", [], []), {
    type: "solved_cancelled",
    id: message.id
  })
};
workerScope.onmessage = async (event) => {
  const message = event.data;
  try {
    const handler = handlers[message.type], response = await handler(message);
    response && workerScope.postMessage(response);
  } catch (error) {
    console.error("[ortools_worker] request failed", message?.type, error), workerScope.postMessage({
      type: "error",
      id: message?.id ?? 0,
      error: String(error)
    });
  }
};
