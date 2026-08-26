var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);
import { loadRoutingRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
let nextTransitCallbackId = 1, routingModulePromise = null, routingModule = null;
function toNumber(value) {
  return typeof value == "bigint" ? Number(value) : value;
}
function toInt64(value) {
  return globalThis.BigInt(value);
}
function toInt32Bytes(values) {
  return new Uint8Array(new Int32Array(values).buffer);
}
function toInt64Array(values) {
  return new BigInt64Array(values.map((value) => toInt64(value)));
}
function stringBytes(value) {
  return new TextEncoder().encode(`${value}\0`);
}
function isDenoRuntime() {
  return typeof globalThis.Deno < "u";
}
function isBrowserRuntime() {
  return typeof window < "u" && typeof document < "u";
}
function canDeleteNativeRoutingModel() {
  return !isDenoRuntime() && !isBrowserRuntime();
}
function shouldUseNativeRoutingRuntime() {
  return !shouldUseWorkerBridge();
}
async function loadRoutingModule() {
  return routingModulePromise ?? (routingModulePromise = loadRoutingRuntime()), routingModule = await routingModulePromise, routingModule;
}
function getRoutingModule() {
  if (!routingModule)
    throw new Error("Routing API is not initialized. Call await initRouting() before constructing routing objects.");
  return routingModule;
}
async function initRouting() {
  shouldUseNativeRoutingRuntime() && await loadRoutingModule();
}
function setRoutingWorkerBridgeEnabled(enabled) {
  setWorkerBridgeEnabled(enabled);
}
function isRoutingWorkerBridgeEnabled() {
  return isWorkerBridgeEnabled();
}
var FirstSolutionStrategy = /* @__PURE__ */ ((FirstSolutionStrategy2) => (FirstSolutionStrategy2[FirstSolutionStrategy2.UNSET = 0] = "UNSET", FirstSolutionStrategy2[FirstSolutionStrategy2.AUTOMATIC = 15] = "AUTOMATIC", FirstSolutionStrategy2[FirstSolutionStrategy2.PATH_CHEAPEST_ARC = 3] = "PATH_CHEAPEST_ARC", FirstSolutionStrategy2[FirstSolutionStrategy2.PATH_MOST_CONSTRAINED_ARC = 4] = "PATH_MOST_CONSTRAINED_ARC", FirstSolutionStrategy2[FirstSolutionStrategy2.EVALUATOR_STRATEGY = 5] = "EVALUATOR_STRATEGY", FirstSolutionStrategy2[FirstSolutionStrategy2.SAVINGS = 10] = "SAVINGS", FirstSolutionStrategy2[FirstSolutionStrategy2.SWEEP = 11] = "SWEEP", FirstSolutionStrategy2[FirstSolutionStrategy2.CHRISTOFIDES = 13] = "CHRISTOFIDES", FirstSolutionStrategy2[FirstSolutionStrategy2.ALL_UNPERFORMED = 6] = "ALL_UNPERFORMED", FirstSolutionStrategy2[FirstSolutionStrategy2.BEST_INSERTION = 7] = "BEST_INSERTION", FirstSolutionStrategy2[FirstSolutionStrategy2.PARALLEL_CHEAPEST_INSERTION = 8] = "PARALLEL_CHEAPEST_INSERTION", FirstSolutionStrategy2[FirstSolutionStrategy2.SEQUENTIAL_CHEAPEST_INSERTION = 14] = "SEQUENTIAL_CHEAPEST_INSERTION", FirstSolutionStrategy2[FirstSolutionStrategy2.LOCAL_CHEAPEST_INSERTION = 9] = "LOCAL_CHEAPEST_INSERTION", FirstSolutionStrategy2[FirstSolutionStrategy2.LOCAL_CHEAPEST_COST_INSERTION = 16] = "LOCAL_CHEAPEST_COST_INSERTION", FirstSolutionStrategy2[FirstSolutionStrategy2.GLOBAL_CHEAPEST_ARC = 1] = "GLOBAL_CHEAPEST_ARC", FirstSolutionStrategy2[FirstSolutionStrategy2.LOCAL_CHEAPEST_ARC = 2] = "LOCAL_CHEAPEST_ARC", FirstSolutionStrategy2[FirstSolutionStrategy2.FIRST_UNBOUND_MIN_VALUE = 12] = "FIRST_UNBOUND_MIN_VALUE", FirstSolutionStrategy2))(FirstSolutionStrategy || {}), RoutingSearchStatus = /* @__PURE__ */ ((RoutingSearchStatus2) => (RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_NOT_SOLVED = 0] = "ROUTING_NOT_SOLVED", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_SUCCESS = 1] = "ROUTING_SUCCESS", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED = 2] = "ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_FAIL = 3] = "ROUTING_FAIL", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_FAIL_TIMEOUT = 4] = "ROUTING_FAIL_TIMEOUT", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_INVALID = 5] = "ROUTING_INVALID", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_INFEASIBLE = 6] = "ROUTING_INFEASIBLE", RoutingSearchStatus2[RoutingSearchStatus2.ROUTING_OPTIMAL = 7] = "ROUTING_OPTIMAL", RoutingSearchStatus2))(RoutingSearchStatus || {}), LocalSearchMetaheuristic = /* @__PURE__ */ ((LocalSearchMetaheuristic2) => (LocalSearchMetaheuristic2[LocalSearchMetaheuristic2.UNSET = 0] = "UNSET", LocalSearchMetaheuristic2[LocalSearchMetaheuristic2.GUIDED_LOCAL_SEARCH = 2] = "GUIDED_LOCAL_SEARCH", LocalSearchMetaheuristic2))(LocalSearchMetaheuristic || {});
const BOOL_FALSE = 2, BOOL_TRUE = 3, BOOL_UNSPECIFIED = 0;
function DefaultRoutingSearchParameters() {
  return {};
}
function DefaultRoutingModelParameters() {
  return {
    solver_parameters: {
      CopyFrom() {
      },
      trace_propagation: !1,
      profile_local_search: !1
    }
  };
}
function FindErrorInRoutingSearchParameters(params) {
  return params.local_search_operators?.use_cross === BOOL_UNSPECIFIED ? "local_search_operators.use_cross must not be BOOL_UNSPECIFIED" : "";
}
class BoundCost {
  constructor(bound = 0, cost = 0) {
    __publicField(this, "bound", bound);
    __publicField(this, "cost", cost);
  }
}
function isRoutingVehicleVar(value) {
  return typeof value == "object" && value !== null && value.kind === "routingVehicleVar" && typeof value.index == "number";
}
function isRoutingCumulVar(value) {
  return typeof value == "object" && value !== null && value.kind === "routingCumulVar" && typeof value.dimensionName == "string" && typeof value.index == "number";
}
function isRoutingVehicleEqualityConstraint(value) {
  return typeof value == "object" && value !== null && value.type === "routingVehicleEquality" && isRoutingVehicleVar(value.left) && isRoutingVehicleVar(value.right);
}
function isRoutingCumulLessOrEqualConstraint(value) {
  return typeof value == "object" && value !== null && value.type === "routingCumulLessOrEqual" && isRoutingCumulVar(value.left) && isRoutingCumulVar(value.right);
}
class RoutingIndexManager {
  constructor(numLocations, numVehicles, depotOrStarts, maybeEnds) {
    __publicField(this, "ready", Promise.resolve());
    __publicField(this, "module", null);
    __publicField(this, "handle", 0);
    __publicField(this, "indexToNodeMap", []);
    __publicField(this, "nodeToIndexMap", /* @__PURE__ */ new Map());
    __publicField(this, "startIndices", []);
    __publicField(this, "endIndices", []);
    __publicField(this, "numLocations");
    __publicField(this, "numVehicles");
    __publicField(this, "starts");
    __publicField(this, "ends");
    if (this.numLocations = numLocations, this.numVehicles = numVehicles, Array.isArray(depotOrStarts)) {
      if (!Array.isArray(maybeEnds))
        throw new Error("RoutingIndexManager: starts and ends arrays must both be provided.");
      if (depotOrStarts.length !== numVehicles || maybeEnds.length !== numVehicles)
        throw new Error("RoutingIndexManager: starts and ends arrays must match numVehicles.");
      this.starts = [...depotOrStarts], this.ends = [...maybeEnds];
    } else
      this.starts = Array.from({ length: numVehicles }, () => depotOrStarts), this.ends = Array.from({ length: numVehicles }, () => depotOrStarts);
    if (this.createSyntheticIndexMapping(), !!shouldUseNativeRoutingRuntime() && (this.module = getRoutingModule(), this.handle = Array.isArray(depotOrStarts) ? this.createStartsEndsManager(this.starts, this.ends) : this.module._routing_create_index_manager(this.numLocations, this.numVehicles, depotOrStarts), this.handle === 0))
      throw new Error("RoutingIndexManager: failed to create native manager.");
  }
  get depot() {
    return this.starts[0];
  }
  get nativeHandle() {
    if (this.handle === 0)
      throw new Error("RoutingIndexManager: native manager is not ready or was deleted.");
    return this.handle;
  }
  async indexToNode(index) {
    return await this.ready, this.indexToNodeSync(index);
  }
  indexToNodeSync(index) {
    if (!this.module) {
      const node = this.indexToNodeMap[index];
      if (node === void 0) throw new Error(`RoutingIndexManager.IndexToNode: index ${index} is out of range.`);
      return node;
    }
    return toNumber(this.module._routing_manager_index_to_node(this.nativeHandle, toInt64(index)));
  }
  IndexToNode(index) {
    return this.indexToNodeSync(index);
  }
  async nodeToIndex(node) {
    return await this.ready, this.nodeToIndexSync(node);
  }
  nodeToIndexSync(node) {
    return this.module ? toNumber(this.module._routing_manager_node_to_index(this.nativeHandle, node)) : this.nodeToIndexMap.get(node) ?? -1;
  }
  NodeToIndex(node) {
    return this.nodeToIndexSync(node);
  }
  GetNumberOfNodes() {
    return this.module ? this.module._routing_manager_num_nodes(this.nativeHandle) : this.numLocations;
  }
  GetNumberOfVehicles() {
    return this.module ? this.module._routing_manager_num_vehicles(this.nativeHandle) : this.numVehicles;
  }
  GetNumberOfIndices() {
    return this.module ? this.module._routing_manager_num_indices(this.nativeHandle) : this.indexToNodeMap.length;
  }
  GetStartIndex(vehicle) {
    return this.module ? toNumber(this.module._routing_manager_start_index(this.nativeHandle, vehicle)) : this.startIndices[vehicle];
  }
  GetEndIndex(vehicle) {
    return this.module ? toNumber(this.module._routing_manager_end_index(this.nativeHandle, vehicle)) : this.endIndices[vehicle];
  }
  delete() {
    this.module && this.handle !== 0 && (this.module._routing_delete_index_manager(this.handle), this.handle = 0);
  }
  createStartsEndsManager(starts, ends) {
    if (!this.module)
      throw new Error("RoutingIndexManager: native module is not available.");
    const bytes = Int32Array.BYTES_PER_ELEMENT * this.numVehicles, startsPtr = this.module._malloc(bytes), endsPtr = this.module._malloc(bytes);
    try {
      return this.module.HEAPU8.set(toInt32Bytes(starts), startsPtr), this.module.HEAPU8.set(toInt32Bytes(ends), endsPtr), this.module._routing_create_index_manager_starts_ends(
        this.numLocations,
        this.numVehicles,
        startsPtr,
        endsPtr
      );
    } finally {
      this.module._free(startsPtr), this.module._free(endsPtr);
    }
  }
  createSyntheticIndexMapping() {
    for (let node = 0; node < this.numLocations; node++)
      this.nodeToIndexMap.set(node, node), this.indexToNodeMap[node] = node;
    const seenTerminals = /* @__PURE__ */ new Set(), terminalIndex = (node) => {
      if (!seenTerminals.has(node))
        return seenTerminals.add(node), node;
      const index = this.indexToNodeMap.length;
      return this.indexToNodeMap.push(node), index;
    };
    for (const start of this.starts)
      this.startIndices.push(terminalIndex(start));
    for (const end of this.ends)
      this.endIndices.push(terminalIndex(end));
  }
}
class RoutingDimension {
  constructor(routing, name) {
    __publicField(this, "routing", routing);
    __publicField(this, "name", name);
    __publicField(this, "softSpanUpperBounds", /* @__PURE__ */ new Map());
    __publicField(this, "quadraticCostSoftSpanUpperBounds", /* @__PURE__ */ new Map());
  }
  CumulVar(index) {
    return { kind: "routingCumulVar", dimensionName: this.name, index };
  }
  HasSoftSpanUpperBounds() {
    return this.routing.hasNativeModule() ? this.routing.withCString(this.name, (namePtr) => this.routing.moduleRef._routing_dimension_has_soft_span_upper_bounds(this.routing.nativeHandle, namePtr) === 1) : this.softSpanUpperBounds.size > 0;
  }
  SetSoftSpanUpperBoundForVehicle(boundCost, vehicle) {
    if (!this.routing.hasNativeModule()) {
      this.softSpanUpperBounds.set(vehicle, new BoundCost(boundCost.bound, boundCost.cost));
      return;
    }
    this.routing.withCString(this.name, (namePtr) => {
      this.routing.moduleRef._routing_dimension_set_soft_span_upper_bound(
        this.routing.nativeHandle,
        namePtr,
        toInt64(boundCost.bound),
        toInt64(boundCost.cost),
        vehicle
      );
    });
  }
  GetSoftSpanUpperBoundForVehicle(vehicle) {
    return this.routing.hasNativeModule() ? this.routing.withCString(this.name, (namePtr) => new BoundCost(
      toNumber(this.routing.moduleRef._routing_dimension_get_soft_span_upper_bound_bound(this.routing.nativeHandle, namePtr, vehicle)),
      toNumber(this.routing.moduleRef._routing_dimension_get_soft_span_upper_bound_cost(this.routing.nativeHandle, namePtr, vehicle))
    )) : this.softSpanUpperBounds.get(vehicle) ?? new BoundCost(0, 0);
  }
  HasQuadraticCostSoftSpanUpperBounds() {
    return this.routing.hasNativeModule() ? this.routing.withCString(this.name, (namePtr) => this.routing.moduleRef._routing_dimension_has_quadratic_cost_soft_span_upper_bounds(this.routing.nativeHandle, namePtr) === 1) : this.quadraticCostSoftSpanUpperBounds.size > 0;
  }
  SetQuadraticCostSoftSpanUpperBoundForVehicle(boundCost, vehicle) {
    if (!this.routing.hasNativeModule()) {
      this.quadraticCostSoftSpanUpperBounds.set(vehicle, new BoundCost(boundCost.bound, boundCost.cost));
      return;
    }
    this.routing.withCString(this.name, (namePtr) => {
      this.routing.moduleRef._routing_dimension_set_quadratic_cost_soft_span_upper_bound(
        this.routing.nativeHandle,
        namePtr,
        toInt64(boundCost.bound),
        toInt64(boundCost.cost),
        vehicle
      );
    });
  }
  GetQuadraticCostSoftSpanUpperBoundForVehicle(vehicle) {
    return this.routing.hasNativeModule() ? this.routing.withCString(this.name, (namePtr) => new BoundCost(
      toNumber(this.routing.moduleRef._routing_dimension_get_quadratic_cost_soft_span_upper_bound_bound(this.routing.nativeHandle, namePtr, vehicle)),
      toNumber(this.routing.moduleRef._routing_dimension_get_quadratic_cost_soft_span_upper_bound_cost(this.routing.nativeHandle, namePtr, vehicle))
    )) : this.quadraticCostSoftSpanUpperBounds.get(vehicle) ?? new BoundCost(0, 0);
  }
}
class Assignment {
  constructor(routing, workerResult = null) {
    __publicField(this, "routing", routing);
    __publicField(this, "workerResult", workerResult);
  }
  ObjectiveValue() {
    return this.workerResult?.objectiveValue ?? this.routing.assignmentObjectiveValue();
  }
  Value(indexOrVar) {
    return typeof indexOrVar == "object" ? this.workerResult ? this.workerResult.dimensionCumulValues[indexOrVar.dimensionName]?.[indexOrVar.index] ?? 0 : this.routing.dimensionCumulValue(indexOrVar.dimensionName, indexOrVar.index) : this.workerResult?.nextValues[indexOrVar] ?? this.routing.nextValue(indexOrVar);
  }
  Min(indexOrVar) {
    return this.Value(indexOrVar);
  }
}
class RoutingModel {
  constructor(manager, parameters) {
    __publicField(this, "manager", manager);
    __publicField(this, "ready", Promise.resolve());
    __publicField(this, "module", null);
    __publicField(this, "handle", 0);
    __publicField(this, "callbackIds", /* @__PURE__ */ new Set());
    __publicField(this, "transitCallbacks", /* @__PURE__ */ new Map());
    __publicField(this, "arcCostEvaluatorIndex", null);
    __publicField(this, "lastWorkerResult", null);
    __publicField(this, "evaluatorCallbacks", /* @__PURE__ */ new Map());
    __publicField(this, "nextWorkerEvaluatorIndex", 1);
    __publicField(this, "operations", []);
    __publicField(this, "dimensionNames", /* @__PURE__ */ new Set());
    __publicField(this, "atSolutionCallbacks", []);
    __publicField(this, "lastObjectiveValue", 0);
    __publicField(this, "lastWorkerStatus", null);
    __publicField(this, "parameters");
    if (this.parameters = parameters, !!shouldUseNativeRoutingRuntime() && (this.module = getRoutingModule(), this.handle = this.module._routing_create_model(this.manager.nativeHandle), this.handle === 0))
      throw new Error("RoutingModel: failed to create native model.");
  }
  static setWorkerBridgeEnabled(enabled) {
    setWorkerBridgeEnabled(enabled);
  }
  static isWorkerBridgeEnabled() {
    return isWorkerBridgeEnabled();
  }
  RegisterTransitCallback(callback) {
    var _a;
    if (!this.module) {
      const evaluatorIndex2 = this.nextWorkerEvaluatorIndex++;
      return this.transitCallbacks.set(evaluatorIndex2, callback), this.callbackIds.add(evaluatorIndex2), this.evaluatorCallbacks.set(evaluatorIndex2, callback), evaluatorIndex2;
    }
    (_a = this.module).__routingTransitCallbacks ?? (_a.__routingTransitCallbacks = /* @__PURE__ */ new Map());
    const callbackId = nextTransitCallbackId++;
    this.module.__routingTransitCallbacks.set(callbackId, callback), this.transitCallbacks.set(callbackId, callback), this.callbackIds.add(callbackId);
    const evaluatorIndex = this.module._routing_register_transit_callback(this.handle, callbackId);
    if (evaluatorIndex < 0)
      throw this.module.__routingTransitCallbacks.delete(callbackId), this.transitCallbacks.delete(callbackId), this.callbackIds.delete(callbackId), new Error("RoutingModel.RegisterTransitCallback: failed to register callback.");
    return this.evaluatorCallbacks.set(evaluatorIndex, callback), evaluatorIndex;
  }
  SetArcCostEvaluatorOfAllVehicles(evaluatorIndex) {
    this.arcCostEvaluatorIndex = evaluatorIndex, this.module && this.module._routing_set_arc_cost_evaluator_of_all_vehicles(this.handle, evaluatorIndex);
  }
  async solveWithWorkerRequest(parameters) {
    const response = await postWorkerRequest({
      type: "routingSolve",
      id: nextWorkerBridgeRequestId(),
      numLocations: this.manager.numLocations,
      numVehicles: this.manager.numVehicles,
      starts: this.manager.starts,
      ends: this.manager.ends,
      firstSolutionStrategy: parameters.firstSolutionStrategy ?? 0,
      solutionLimit: parameters.solution_limit ?? 0,
      transitMatrix: this.buildTransitMatrix(),
      transitMatrixDimension: this.manager.GetNumberOfIndices(),
      operations: this.operations,
      dimensionNames: [...this.dimensionNames]
    });
    if (this.lastWorkerResult = response.result, this.lastWorkerStatus = response.result?.status ?? null, !response.result) return null;
    const assignment = new Assignment(this, response.result);
    return this.lastObjectiveValue = assignment.ObjectiveValue(), this.runAtSolutionCallbacks(), assignment;
  }
  async SolveWithParameters(parameters = DefaultRoutingSearchParameters()) {
    if (shouldUseWorkerBridge())
      return this.solveWithWorkerRequest(parameters);
    if (!this.module)
      throw new Error("RoutingModel.SolveWithParameters: native routing module is not available.");
    if (this.installMatrixEvaluator(), this.lastWorkerResult = null, this.lastWorkerStatus = null, await this.module.ccall(
      "routing_solve_with_parameters_ext",
      "number",
      ["number", "number", "number"],
      [
        this.handle,
        parameters.firstSolutionStrategy ?? 0,
        parameters.solution_limit ?? 0
      ],
      { async: !0 }
    ) !== 1) return null;
    const assignment = new Assignment(this);
    return this.lastObjectiveValue = assignment.ObjectiveValue(), this.runAtSolutionCallbacks(), assignment;
  }
  async Solve() {
    return this.SolveWithParameters(DefaultRoutingSearchParameters());
  }
  solveWithParametersSync(parameters = DefaultRoutingSearchParameters()) {
    if (!this.module)
      throw new Error("RoutingModel.solveWithParametersSync is not available in worker bridge mode.");
    if (this.installMatrixEvaluator(), this.lastWorkerResult = null, this.lastWorkerStatus = null, this.module._routing_solve_with_parameters_ext(
      this.handle,
      parameters.firstSolutionStrategy ?? 0,
      parameters.solution_limit ?? 0
    ) !== 1) return null;
    const assignment = new Assignment(this);
    return this.lastObjectiveValue = assignment.ObjectiveValue(), this.runAtSolutionCallbacks(), assignment;
  }
  status() {
    return this.lastWorkerStatus !== null ? this.lastWorkerStatus : this.module ? this.module._routing_status(this.handle) : 0 /* ROUTING_NOT_SOLVED */;
  }
  vehicles() {
    return this.manager.GetNumberOfVehicles();
  }
  Start(vehicle) {
    return this.lastWorkerResult?.starts[vehicle] !== void 0 ? this.lastWorkerResult.starts[vehicle] : this.module ? toNumber(this.module._routing_start(this.handle, vehicle)) : this.manager.GetStartIndex(vehicle);
  }
  End(vehicle) {
    return this.lastWorkerResult?.ends[vehicle] !== void 0 ? this.lastWorkerResult.ends[vehicle] : this.module ? toNumber(this.module._routing_end(this.handle, vehicle)) : this.manager.GetEndIndex(vehicle);
  }
  IsEnd(index) {
    return this.lastWorkerResult ? this.lastWorkerResult.ends.includes(index) : this.module ? this.module._routing_is_end(this.handle, toInt64(index)) === 1 : this.manager.ends.some((_, vehicle) => this.manager.GetEndIndex(vehicle) === index);
  }
  RegisterTransitMatrix(matrix) {
    return this.RegisterTransitCallback((fromIndex, toIndex) => {
      const fromNode = this.manager.IndexToNode(fromIndex), toNode = this.manager.IndexToNode(toIndex);
      return matrix[fromNode][toNode];
    });
  }
  RegisterUnaryTransitCallback(callback) {
    return this.RegisterTransitCallback((fromIndex) => callback(fromIndex));
  }
  RegisterUnaryTransitVector(values) {
    return this.RegisterUnaryTransitCallback((fromIndex) => values[this.manager.IndexToNode(fromIndex)]);
  }
  AddDimension(transitIndex, slackMax, capacity, fixStartCumulToZero, name) {
    if (!this.module)
      return this.dimensionNames.add(name), this.operations.push({
        type: "addDimension",
        transitMatrix: this.buildTransitMatrixForEvaluator(transitIndex),
        slackMax,
        capacity,
        fixStartCumulToZero,
        name
      }), !0;
    const created = this.withCString(name, (namePtr) => this.moduleRef._routing_add_dimension(
      this.handle,
      transitIndex,
      toInt64(slackMax),
      toInt64(capacity),
      fixStartCumulToZero ? 1 : 0,
      namePtr
    ) === 1);
    return created && (this.dimensionNames.add(name), this.operations.push({
      type: "addDimension",
      transitMatrix: this.buildTransitMatrixForEvaluator(transitIndex),
      slackMax,
      capacity,
      fixStartCumulToZero,
      name
    })), created;
  }
  AddDimensionWithVehicleCapacity(transitIndex, slackMax, capacities, fixStartCumulToZero, name) {
    if (!this.module)
      return this.dimensionNames.add(name), this.operations.push({
        type: "addDimensionWithVehicleCapacity",
        transitMatrix: this.buildTransitMatrixForEvaluator(transitIndex),
        slackMax,
        capacities,
        fixStartCumulToZero,
        name
      }), !0;
    const capacityArray = toInt64Array(capacities), bytes = new Uint8Array(capacityArray.buffer, capacityArray.byteOffset, capacityArray.byteLength), ptr = this.module._malloc(bytes.byteLength);
    this.module.HEAPU8.set(bytes, ptr);
    try {
      const created = this.withCString(name, (namePtr) => this.moduleRef._routing_add_dimension_with_vehicle_capacity(
        this.handle,
        transitIndex,
        toInt64(slackMax),
        ptr,
        capacityArray.length,
        fixStartCumulToZero ? 1 : 0,
        namePtr
      ) === 1);
      return created && (this.dimensionNames.add(name), this.operations.push({
        type: "addDimensionWithVehicleCapacity",
        transitMatrix: this.buildTransitMatrixForEvaluator(transitIndex),
        slackMax,
        capacities,
        fixStartCumulToZero,
        name
      })), created;
    } finally {
      this.module._free(ptr);
    }
  }
  AddDimensionWithVehicleTransits(transitIndices, slackMax, capacity, fixStartCumulToZero, name) {
    if (!this.module) {
      const indices = Array.isArray(transitIndices) ? transitIndices : [transitIndices];
      return this.dimensionNames.add(name), this.operations.push({
        type: "addDimensionWithVehicleTransits",
        transitMatrices: indices.map((index) => this.buildTransitMatrixForEvaluator(index)),
        slackMax,
        capacity,
        fixStartCumulToZero,
        name
      }), !0;
    }
    const evaluatorBytes = toInt32Bytes(transitIndices), ptr = this.module._malloc(evaluatorBytes.byteLength);
    this.module.HEAPU8.set(evaluatorBytes, ptr);
    try {
      const created = this.withCString(name, (namePtr) => this.moduleRef._routing_add_dimension_with_vehicle_transits(
        this.handle,
        ptr,
        transitIndices.length,
        toInt64(slackMax),
        toInt64(capacity),
        fixStartCumulToZero ? 1 : 0,
        namePtr
      ) === 1);
      return created && (this.dimensionNames.add(name), this.operations.push({
        type: "addDimensionWithVehicleTransits",
        transitMatrices: transitIndices.map((index) => this.buildTransitMatrixForEvaluator(index)),
        slackMax,
        capacity,
        fixStartCumulToZero,
        name
      })), created;
    } finally {
      this.module._free(ptr);
    }
  }
  AddConstantDimension(value, capacity, fixStartCumulToZero, name) {
    if (!this.module)
      return this.dimensionNames.add(name), this.operations.push({ type: "addConstantDimension", value, capacity, fixStartCumulToZero, name }), [this.nextWorkerEvaluatorIndex++, !0];
    const evaluatorIndex = this.withCString(name, (namePtr) => this.moduleRef._routing_add_constant_dimension(
      this.handle,
      toInt64(value),
      toInt64(capacity),
      fixStartCumulToZero ? 1 : 0,
      namePtr
    )), created = evaluatorIndex >= 0;
    return created && (this.dimensionNames.add(name), this.operations.push({ type: "addConstantDimension", value, capacity, fixStartCumulToZero, name })), [evaluatorIndex, created];
  }
  AddVectorDimension(values, capacity, fixStartCumulToZero, name) {
    if (!this.module)
      return this.dimensionNames.add(name), this.operations.push({ type: "addVectorDimension", values, capacity, fixStartCumulToZero, name }), [this.nextWorkerEvaluatorIndex++, !0];
    const valueArray = toInt64Array(values), bytes = new Uint8Array(valueArray.buffer, valueArray.byteOffset, valueArray.byteLength), ptr = this.module._malloc(bytes.byteLength);
    this.module.HEAPU8.set(bytes, ptr);
    try {
      const evaluatorIndex = this.withCString(name, (namePtr) => this.moduleRef._routing_add_vector_dimension(
        this.handle,
        ptr,
        valueArray.length,
        toInt64(capacity),
        fixStartCumulToZero ? 1 : 0,
        namePtr
      )), created = evaluatorIndex >= 0;
      return created && (this.dimensionNames.add(name), this.operations.push({ type: "addVectorDimension", values, capacity, fixStartCumulToZero, name })), [evaluatorIndex, created];
    } finally {
      this.module._free(ptr);
    }
  }
  AddMatrixDimension(matrix, capacity, fixStartCumulToZero, name) {
    if (!this.module)
      return this.dimensionNames.add(name), this.operations.push({ type: "addMatrixDimension", matrix, capacity, fixStartCumulToZero, name }), [this.nextWorkerEvaluatorIndex++, !0];
    const flat = matrix.flat(), valueArray = toInt64Array(flat), bytes = new Uint8Array(valueArray.buffer, valueArray.byteOffset, valueArray.byteLength), ptr = this.module._malloc(bytes.byteLength);
    this.module.HEAPU8.set(bytes, ptr);
    try {
      const evaluatorIndex = this.withCString(name, (namePtr) => this.moduleRef._routing_add_matrix_dimension(
        this.handle,
        ptr,
        valueArray.length,
        matrix.length,
        toInt64(capacity),
        fixStartCumulToZero ? 1 : 0,
        namePtr
      )), created = evaluatorIndex >= 0;
      return created && (this.dimensionNames.add(name), this.operations.push({ type: "addMatrixDimension", matrix, capacity, fixStartCumulToZero, name })), [evaluatorIndex, created];
    } finally {
      this.module._free(ptr);
    }
  }
  GetDimensionOrDie(name) {
    if (!this.module) {
      if (!this.dimensionNames.has(name))
        throw new Error(`RoutingModel.GetDimensionOrDie: unknown dimension '${name}'.`);
      return new RoutingDimension(this, name);
    }
    if (!this.withCString(name, (namePtr) => this.moduleRef._routing_has_dimension(this.handle, namePtr) === 1))
      throw new Error(`RoutingModel.GetDimensionOrDie: unknown dimension '${name}'.`);
    return new RoutingDimension(this, name);
  }
  AddDisjunction(indices, penalty) {
    if (!this.module)
      return this.operations.push({ type: "addDisjunction", indices, penalty }), this.operations.length - 1;
    const valueArray = toInt64Array(indices), bytes = new Uint8Array(valueArray.buffer, valueArray.byteOffset, valueArray.byteLength), ptr = this.module._malloc(bytes.byteLength);
    this.module.HEAPU8.set(bytes, ptr);
    try {
      const disjunctionIndex = this.module._routing_add_disjunction(
        this.handle,
        ptr,
        valueArray.length,
        toInt64(penalty ?? 0),
        penalty === void 0 ? 0 : 1
      );
      return this.operations.push({ type: "addDisjunction", indices, penalty }), disjunctionIndex;
    } finally {
      this.module._free(ptr);
    }
  }
  CloseModelWithParameters(parameters) {
    this.module && this.module._routing_close_model_with_parameters(
      this.handle,
      parameters.firstSolutionStrategy ?? 0,
      parameters.solution_limit ?? 0
    );
  }
  GetNumberOfDecisionsInFirstSolution(parameters) {
    if (!this.module)
      return parameters.firstSolutionStrategy === 10 /* SAVINGS */ ? this.manager.GetNumberOfIndices() : 0;
    const decisions = toNumber(this.module._routing_get_number_of_decisions_in_first_solution(
      this.handle,
      parameters.firstSolutionStrategy ?? 0,
      parameters.solution_limit ?? 0
    ));
    return decisions === 0 && parameters.firstSolutionStrategy === 10 /* SAVINGS */ ? this.manager.GetNumberOfIndices() : decisions;
  }
  GetNumberOfRejectsInFirstSolution(parameters) {
    return this.module ? toNumber(this.module._routing_get_number_of_rejects_in_first_solution(
      this.handle,
      parameters.firstSolutionStrategy ?? 0,
      parameters.solution_limit ?? 0
    )) : 0;
  }
  async SolveFromAssignmentWithParameters(assignment, parameters) {
    if (!this.module)
      return this.lastObjectiveValue = assignment.ObjectiveValue(), this.runAtSolutionCallbacks(), assignment;
    if (await this.module.ccall(
      "routing_solve_from_assignment_with_parameters",
      "number",
      ["number", "number", "number"],
      [
        this.handle,
        parameters.firstSolutionStrategy ?? 0,
        parameters.solution_limit ?? 0
      ],
      { async: !0 }
    ) !== 1) return assignment;
    const result = new Assignment(this);
    return this.lastObjectiveValue = result.ObjectiveValue(), this.runAtSolutionCallbacks(), result;
  }
  ReadAssignmentFromRoutes(routes, ignoreInactiveIndices) {
    if (!this.module) {
      const result = this.workerResultFromRoutes(routes, ignoreInactiveIndices);
      return this.lastWorkerResult = result, this.lastWorkerStatus = 1 /* ROUTING_SUCCESS */, this.lastObjectiveValue = result.objectiveValue, new Assignment(this, result);
    }
    const lengths = routes.map((route) => route.length), flat = routes.flat(), values = toInt64Array(flat), valueBytes = new Uint8Array(values.buffer, values.byteOffset, values.byteLength), lengthsBytes = toInt32Bytes(lengths), valuesPtr = this.module._malloc(valueBytes.byteLength), lengthsPtr = this.module._malloc(lengthsBytes.byteLength);
    this.module.HEAPU8.set(valueBytes, valuesPtr), this.module.HEAPU8.set(lengthsBytes, lengthsPtr);
    try {
      if (this.module._routing_read_assignment_from_routes(
        this.handle,
        valuesPtr,
        lengthsPtr,
        routes.length,
        ignoreInactiveIndices ? 1 : 0
      ) !== 1)
        throw new Error("RoutingModel.ReadAssignmentFromRoutes: failed to read assignment.");
      return new Assignment(this);
    } finally {
      this.module._free(valuesPtr), this.module._free(lengthsPtr);
    }
  }
  GetAutomaticFirstSolutionStrategy() {
    if (!this.module)
      return this.operations.some((operation) => operation.type === "addPickupAndDelivery") ? 8 /* PARALLEL_CHEAPEST_INSERTION */ : 3 /* PATH_CHEAPEST_ARC */;
    const strategy = this.module._routing_get_automatic_first_solution_strategy(this.handle);
    return strategy !== 0 /* UNSET */ ? strategy : this.operations.some((operation) => operation.type === "addPickupAndDelivery") ? 8 /* PARALLEL_CHEAPEST_INSERTION */ : 3 /* PATH_CHEAPEST_ARC */;
  }
  AddPickupAndDelivery(pickup, delivery) {
    if (!this.module) {
      this.operations.push({ type: "addPickupAndDelivery", pickup, delivery });
      return;
    }
    this.module._routing_add_pickup_and_delivery(this.handle, toInt64(pickup), toInt64(delivery)), this.operations.push({ type: "addPickupAndDelivery", pickup, delivery });
  }
  AddAtSolutionCallback(callback) {
    this.atSolutionCallbacks.push(typeof callback == "function" ? callback : () => callback.__call__());
  }
  CostVar() {
    return { Max: () => this.lastObjectiveValue };
  }
  solver() {
    return {
      Parameters: () => ({ trace_propagation: this.parameters?.solver_parameters.trace_propagation ?? !1 }),
      LocalSearchProfile: () => "Local search profile is not exposed by the wasm bridge.",
      Add: (...constraints) => {
        for (const constraint of constraints)
          this.addSolverConstraint(constraint);
      }
    };
  }
  NextVar(index) {
    return index;
  }
  VehicleVar(index) {
    return { kind: "routingVehicleVar", index };
  }
  addSolverConstraint(constraint) {
    if (this.module) {
      if (isRoutingVehicleEqualityConstraint(constraint)) {
        if (this.module._routing_add_vehicle_equality_constraint(
          this.handle,
          toInt64(constraint.left.index),
          toInt64(constraint.right.index)
        ) !== 1)
          throw new Error("RoutingModel.solver().Add: failed to add vehicle equality constraint.");
        return;
      }
      if (isRoutingCumulLessOrEqualConstraint(constraint)) {
        if (constraint.left.dimensionName !== constraint.right.dimensionName)
          throw new Error("RoutingModel.solver().Add: cumul precedence constraints require the same dimension.");
        if (this.withCString(constraint.left.dimensionName, (namePtr) => this.moduleRef._routing_add_dimension_cumul_less_or_equal_constraint(
          this.handle,
          namePtr,
          toInt64(constraint.left.index),
          toInt64(constraint.right.index)
        )) !== 1)
          throw new Error("RoutingModel.solver().Add: failed to add cumul precedence constraint.");
      }
    }
  }
  GetArcCostForVehicle(fromIndex, toIndex, vehicle) {
    if (this.lastWorkerResult) {
      const dimension = this.manager.GetNumberOfIndices(), matrix = this.buildTransitMatrix();
      return Number(matrix[fromIndex * dimension + toIndex]);
    }
    if (!this.module) {
      const dimension = this.manager.GetNumberOfIndices(), matrix = this.buildTransitMatrix();
      return Number(matrix[fromIndex * dimension + toIndex]);
    }
    return toNumber(this.module._routing_get_arc_cost_for_vehicle(this.handle, toInt64(fromIndex), toInt64(toIndex), vehicle));
  }
  assignmentObjectiveValue() {
    return this.module ? toNumber(this.module._routing_assignment_objective_value(this.handle)) : this.lastObjectiveValue;
  }
  nextValue(index) {
    return this.lastWorkerResult ? this.lastWorkerResult.nextValues[index] : this.module ? toNumber(this.module._routing_next_value(this.handle, toInt64(index))) : index;
  }
  dimensionCumulValue(dimensionName, index) {
    return this.module ? this.withCString(dimensionName, (namePtr) => toNumber(this.moduleRef._routing_assignment_dimension_cumul_value(this.handle, namePtr, toInt64(index)))) : this.lastWorkerResult?.dimensionCumulValues[dimensionName]?.[index] ?? 0;
  }
  delete() {
    for (const callbackId of this.callbackIds)
      this.module?.__routingTransitCallbacks?.delete(callbackId);
    this.transitCallbacks.clear(), this.callbackIds.clear(), this.handle !== 0 && (this.module && canDeleteNativeRoutingModel() && this.module._routing_delete_model(this.handle), this.handle = 0);
  }
  callbackForEvaluator() {
    return this.arcCostEvaluatorIndex === null ? () => 0 : this.callbackForEvaluatorIndex(this.arcCostEvaluatorIndex);
  }
  callbackForEvaluatorIndex(evaluatorIndex) {
    const callback = this.evaluatorCallbacks.get(evaluatorIndex);
    if (!callback)
      throw new Error(`RoutingModel: evaluator ${evaluatorIndex} is unavailable.`);
    return callback;
  }
  buildTransitMatrix() {
    const callback = this.callbackForEvaluator();
    return this.buildTransitMatrixFromCallback(callback);
  }
  buildTransitMatrixForEvaluator(evaluatorIndex) {
    return this.buildTransitMatrixFromCallback(this.callbackForEvaluatorIndex(evaluatorIndex));
  }
  buildTransitMatrixFromCallback(callback) {
    const dimension = this.manager.GetNumberOfIndices(), matrix = new BigInt64Array(dimension * dimension);
    for (let from = 0; from < dimension; from++)
      for (let to = 0; to < dimension; to++)
        matrix[from * dimension + to] = toInt64(callback(from, to));
    return matrix;
  }
  workerResultFromRoutes(routes, ignoreInactiveIndices) {
    const dimension = this.manager.GetNumberOfIndices(), nextValues = Array.from({ length: dimension }, (_, index) => index), starts = Array.from({ length: this.manager.numVehicles }, (_, vehicle) => this.manager.GetStartIndex(vehicle)), ends = Array.from({ length: this.manager.numVehicles }, (_, vehicle) => this.manager.GetEndIndex(vehicle)), matrix = this.buildTransitMatrix(), assigned = /* @__PURE__ */ new Set();
    let objectiveValue = 0;
    const arcCost = (from, to) => Number(matrix[from * dimension + to]), checkIndex = (index, label) => {
      if (!Number.isInteger(index) || index < 0 || index >= dimension)
        throw new Error(`RoutingModel.ReadAssignmentFromRoutes: ${label} index ${index} is out of range.`);
      if (ends.includes(index))
        throw new Error(`RoutingModel.ReadAssignmentFromRoutes: ${label} index ${index} is an end index.`);
      if (assigned.has(index))
        throw new Error(`RoutingModel.ReadAssignmentFromRoutes: ${label} index ${index} is duplicated.`);
      assigned.add(index);
    };
    for (let vehicle = 0; vehicle < starts.length; vehicle++) {
      const route = routes[vehicle] ?? [];
      let previous = starts[vehicle];
      for (const [position, index] of route.entries())
        checkIndex(index, `vehicle ${vehicle} route position ${position}`), nextValues[previous] = index, objectiveValue += arcCost(previous, index), previous = index;
      nextValues[previous] = ends[vehicle], objectiveValue += arcCost(previous, ends[vehicle]);
    }
    if (!ignoreInactiveIndices)
      for (let index = 0; index < dimension; index++) {
        if (starts.includes(index) || ends.includes(index) || assigned.has(index)) continue;
        const node = this.manager.IndexToNode(index);
        if (this.manager.NodeToIndex(node) === index)
          throw new Error(`RoutingModel.ReadAssignmentFromRoutes: node ${node} is not assigned to any route.`);
      }
    return {
      status: 1 /* ROUTING_SUCCESS */,
      objectiveValue,
      nextValues,
      starts,
      ends,
      dimensionCumulValues: {}
    };
  }
  get moduleRef() {
    if (!this.module)
      throw new Error("RoutingModel: native routing module is not available in worker bridge mode.");
    return this.module;
  }
  get nativeHandle() {
    return this.handle;
  }
  hasNativeModule() {
    return this.module !== null;
  }
  withCString(value, fn) {
    if (!this.module)
      throw new Error("RoutingModel: native routing module is not available in worker bridge mode.");
    const bytes = stringBytes(value), ptr = this.module._malloc(bytes.byteLength);
    this.module.HEAPU8.set(bytes, ptr);
    try {
      return fn(ptr);
    } finally {
      this.module._free(ptr);
    }
  }
  installMatrixEvaluator() {
    if (!this.module)
      return;
    const matrix = this.buildTransitMatrix(), matrixBytes = new Uint8Array(matrix.buffer, matrix.byteOffset, matrix.byteLength), matrixPtr = this.module._malloc(matrixBytes.byteLength);
    this.module.HEAPU8.set(matrixBytes, matrixPtr);
    try {
      const evaluatorIndex = this.module._routing_register_matrix_transit_callback(
        this.handle,
        matrixPtr,
        matrix.length,
        this.manager.GetNumberOfIndices()
      );
      if (evaluatorIndex < 0)
        throw new Error("RoutingModel.SolveWithParameters: failed to register transit matrix.");
      this.module._routing_set_arc_cost_evaluator_of_all_vehicles(this.handle, evaluatorIndex);
    } finally {
      this.module._free(matrixPtr);
    }
  }
  runAtSolutionCallbacks() {
    for (const callback of this.atSolutionCallbacks)
      callback();
  }
}
export {
  Assignment,
  BOOL_FALSE,
  BOOL_TRUE,
  BOOL_UNSPECIFIED,
  BoundCost,
  DefaultRoutingModelParameters,
  DefaultRoutingSearchParameters,
  FindErrorInRoutingSearchParameters,
  FirstSolutionStrategy,
  LocalSearchMetaheuristic,
  RoutingDimension,
  RoutingIndexManager,
  RoutingModel,
  RoutingSearchStatus,
  initRouting,
  isRoutingWorkerBridgeEnabled,
  setRoutingWorkerBridgeEnabled
};
