var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);

// ../javascript/lib/graph_api.ts
import { loadGraphRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
var graphModulePromise = null, graphModule = null;
async function initNetworkFlow() {
  shouldUseWorkerBridge() || (graphModulePromise ?? (graphModulePromise = loadGraphRuntime().then((module) => (graphModule = module, module))), await graphModulePromise);
}
function currentModule() {
  if (!graphModule)
    throw new Error("Network Flow runtime has not been initialized. Call initNetworkFlow() first.");
  return graphModule;
}
function copyFloat64ToHeap(module, values) {
  if (!values.length) return 0;
  let ptr = module._malloc(values.length * Float64Array.BYTES_PER_ELEMENT);
  return new Float64Array(module.HEAPU8.buffer, ptr, values.length).set(values), ptr;
}
function parseResult(value) {
  let result = JSON.parse(value);
  if (!result.ok)
    throw new Error(result.error);
  return result;
}
function assertEqualLengths(name, ...values) {
  let expected = values[0]?.length ?? 0;
  for (let value of values)
    if (value.length !== expected)
      throw new Error(`${name}: all input arrays must have the same length.`);
}
function toNumberArray(values, name) {
  return Array.from(values, (value, index) => {
    if (!Number.isFinite(value) || !Number.isInteger(value))
      throw new Error(`${name}[${index}] must be a finite integer.`);
    return value;
  });
}
function assertIndex(index, length, label) {
  if (!Number.isInteger(index) || index < 0 || index >= length)
    throw new Error(`${label} index ${index} is out of range.`);
}
async function solveMaxFlowDirect(payload) {
  let module = currentModule(), tailsPtr = copyFloat64ToHeap(module, payload.tails), headsPtr = copyFloat64ToHeap(module, payload.heads), capacitiesPtr = copyFloat64ToHeap(module, payload.capacities);
  try {
    return parseResult(await module.ccall(
      "graph_max_flow_solve_serialized",
      "string",
      ["number", "number", "number", "number", "number", "number"],
      [tailsPtr, headsPtr, capacitiesPtr, payload.tails.length, payload.source, payload.sink],
      { async: !0 }
    ));
  } finally {
    tailsPtr && module._free(tailsPtr), headsPtr && module._free(headsPtr), capacitiesPtr && module._free(capacitiesPtr);
  }
}
async function solveMinCostFlowDirect(payload) {
  let module = currentModule(), tailsPtr = copyFloat64ToHeap(module, payload.tails), headsPtr = copyFloat64ToHeap(module, payload.heads), capacitiesPtr = copyFloat64ToHeap(module, payload.capacities), unitCostsPtr = copyFloat64ToHeap(module, payload.unitCosts), suppliesPtr = copyFloat64ToHeap(module, payload.supplies);
  try {
    return parseResult(await module.ccall(
      "graph_min_cost_flow_solve_serialized",
      "string",
      ["number", "number", "number", "number", "number", "number", "number", "number"],
      [
        tailsPtr,
        headsPtr,
        capacitiesPtr,
        unitCostsPtr,
        payload.tails.length,
        suppliesPtr,
        payload.supplies.length,
        payload.solveMaxFlowWithMinCost ? 1 : 0
      ],
      { async: !0 }
    ));
  } finally {
    tailsPtr && module._free(tailsPtr), headsPtr && module._free(headsPtr), capacitiesPtr && module._free(capacitiesPtr), unitCostsPtr && module._free(unitCostsPtr), suppliesPtr && module._free(suppliesPtr);
  }
}
async function solveLinearSumAssignmentDirect(payload) {
  let module = currentModule(), leftNodesPtr = copyFloat64ToHeap(module, payload.leftNodes), rightNodesPtr = copyFloat64ToHeap(module, payload.rightNodes), costsPtr = copyFloat64ToHeap(module, payload.costs);
  try {
    return parseResult(await module.ccall(
      "graph_linear_sum_assignment_solve_serialized",
      "string",
      ["number", "number", "number", "number"],
      [leftNodesPtr, rightNodesPtr, costsPtr, payload.leftNodes.length],
      { async: !0 }
    ));
  } finally {
    leftNodesPtr && module._free(leftNodesPtr), rightNodesPtr && module._free(rightNodesPtr), costsPtr && module._free(costsPtr);
  }
}
async function solveGraphPayload(payload) {
  if (shouldUseWorkerBridge()) {
    let response = await postWorkerRequest({
      type: "graphSolve",
      id: nextWorkerBridgeRequestId(),
      ...payload
    });
    return parseResult(response.result);
  }
  return await initNetworkFlow(), payload.algorithm === "maxFlow" ? await solveMaxFlowDirect(payload) : payload.algorithm === "minCostFlow" ? await solveMinCostFlowDirect(payload) : await solveLinearSumAssignmentDirect(payload);
}
var SimpleMaxFlowStatus = /* @__PURE__ */ ((SimpleMaxFlowStatus2) => (SimpleMaxFlowStatus2[SimpleMaxFlowStatus2.OPTIMAL = 0] = "OPTIMAL", SimpleMaxFlowStatus2[SimpleMaxFlowStatus2.POSSIBLE_OVERFLOW = 1] = "POSSIBLE_OVERFLOW", SimpleMaxFlowStatus2[SimpleMaxFlowStatus2.BAD_INPUT = 2] = "BAD_INPUT", SimpleMaxFlowStatus2[SimpleMaxFlowStatus2.BAD_RESULT = 3] = "BAD_RESULT", SimpleMaxFlowStatus2))(SimpleMaxFlowStatus || {}), SimpleMinCostFlowStatus = /* @__PURE__ */ ((SimpleMinCostFlowStatus2) => (SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.NOT_SOLVED = 0] = "NOT_SOLVED", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.OPTIMAL = 1] = "OPTIMAL", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.FEASIBLE = 2] = "FEASIBLE", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.INFEASIBLE = 3] = "INFEASIBLE", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.UNBALANCED = 4] = "UNBALANCED", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.BAD_RESULT = 5] = "BAD_RESULT", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.BAD_COST_RANGE = 6] = "BAD_COST_RANGE", SimpleMinCostFlowStatus2[SimpleMinCostFlowStatus2.BAD_CAPACITY_RANGE = 7] = "BAD_CAPACITY_RANGE", SimpleMinCostFlowStatus2))(SimpleMinCostFlowStatus || {}), SimpleLinearSumAssignmentStatus = /* @__PURE__ */ ((SimpleLinearSumAssignmentStatus2) => (SimpleLinearSumAssignmentStatus2[SimpleLinearSumAssignmentStatus2.OPTIMAL = 0] = "OPTIMAL", SimpleLinearSumAssignmentStatus2[SimpleLinearSumAssignmentStatus2.INFEASIBLE = 1] = "INFEASIBLE", SimpleLinearSumAssignmentStatus2[SimpleLinearSumAssignmentStatus2.POSSIBLE_OVERFLOW = 2] = "POSSIBLE_OVERFLOW", SimpleLinearSumAssignmentStatus2))(SimpleLinearSumAssignmentStatus || {}), SimpleMaxFlow = class {
  constructor() {
    __publicField(this, "tails", []);
    __publicField(this, "heads", []);
    __publicField(this, "capacities", []);
    __publicField(this, "result", null);
  }
  add_arc_with_capacity(tail, head, capacity) {
    let arc = this.tails.length;
    return this.tails.push(...toNumberArray([tail], "tail")), this.heads.push(...toNumberArray([head], "head")), this.capacities.push(...toNumberArray([capacity], "capacity")), this.result = null, arc;
  }
  addArcWithCapacity(tail, head, capacity) {
    return this.add_arc_with_capacity(tail, head, capacity);
  }
  add_arcs_with_capacity(tails, heads, capacities) {
    let tailValues = toNumberArray(tails, "tails"), headValues = toNumberArray(heads, "heads"), capacityValues = toNumberArray(capacities, "capacities");
    return assertEqualLengths("SimpleMaxFlow.add_arcs_with_capacity", tailValues, headValues, capacityValues), tailValues.map((tail, index) => this.add_arc_with_capacity(tail, headValues[index], capacityValues[index]));
  }
  addArcsWithCapacity(tails, heads, capacities) {
    return this.add_arcs_with_capacity(tails, heads, capacities);
  }
  set_arc_capacity(arc, capacity) {
    assertIndex(arc, this.capacities.length, "arc"), this.capacities[arc] = toNumberArray([capacity], "capacity")[0], this.result = null;
  }
  setArcCapacity(arc, capacity) {
    this.set_arc_capacity(arc, capacity);
  }
  set_arcs_capacity(arcs, capacities) {
    let arcValues = toNumberArray(arcs, "arcs"), capacityValues = toNumberArray(capacities, "capacities");
    assertEqualLengths("SimpleMaxFlow.set_arcs_capacity", arcValues, capacityValues);
    for (let [index, arc] of arcValues.entries()) this.set_arc_capacity(arc, capacityValues[index]);
  }
  setArcsCapacity(arcs, capacities) {
    this.set_arcs_capacity(arcs, capacities);
  }
  num_nodes() {
    return this.tails.reduce((maxNode, tail, index) => Math.max(maxNode, tail, this.heads[index]), -1) + 1;
  }
  numNodes() {
    return this.num_nodes();
  }
  num_arcs() {
    return this.tails.length;
  }
  numArcs() {
    return this.num_arcs();
  }
  tail(arc) {
    return assertIndex(arc, this.tails.length, "arc"), this.tails[arc];
  }
  head(arc) {
    return assertIndex(arc, this.heads.length, "arc"), this.heads[arc];
  }
  capacity(arc) {
    return assertIndex(arc, this.capacities.length, "arc"), this.capacities[arc];
  }
  async solve(source, sink) {
    let result = await solveGraphPayload({
      algorithm: "maxFlow",
      tails: this.tails,
      heads: this.heads,
      capacities: this.capacities,
      source,
      sink
    });
    return this.result = result, result.status;
  }
  optimal_flow() {
    return this.result?.optimalFlow ?? 0;
  }
  optimalFlow() {
    return this.optimal_flow();
  }
  flow(arc) {
    return assertIndex(arc, this.capacities.length, "arc"), this.result?.flows?.[arc] ?? 0;
  }
  flows(arcs) {
    return toNumberArray(arcs, "arcs").map((arc) => this.flow(arc));
  }
  get_source_side_min_cut() {
    return [...this.result?.sourceSideMinCut ?? []];
  }
  getSourceSideMinCut() {
    return this.get_source_side_min_cut();
  }
  get_sink_side_min_cut() {
    return [...this.result?.sinkSideMinCut ?? []];
  }
  getSinkSideMinCut() {
    return this.get_sink_side_min_cut();
  }
};
__publicField(SimpleMaxFlow, "OPTIMAL", 0 /* OPTIMAL */), __publicField(SimpleMaxFlow, "POSSIBLE_OVERFLOW", 1 /* POSSIBLE_OVERFLOW */), __publicField(SimpleMaxFlow, "BAD_INPUT", 2 /* BAD_INPUT */), __publicField(SimpleMaxFlow, "BAD_RESULT", 3 /* BAD_RESULT */);
var SimpleMinCostFlow = class {
  constructor() {
    __publicField(this, "tails", []);
    __publicField(this, "heads", []);
    __publicField(this, "capacities", []);
    __publicField(this, "unitCosts", []);
    __publicField(this, "nodeSupplies", []);
    __publicField(this, "result", null);
  }
  add_arc_with_capacity_and_unit_cost(tail, head, capacity, unitCost) {
    let arc = this.tails.length;
    return this.tails.push(...toNumberArray([tail], "tail")), this.heads.push(...toNumberArray([head], "head")), this.capacities.push(...toNumberArray([capacity], "capacity")), this.unitCosts.push(...toNumberArray([unitCost], "unitCost")), this.result = null, arc;
  }
  addArcWithCapacityAndUnitCost(tail, head, capacity, unitCost) {
    return this.add_arc_with_capacity_and_unit_cost(tail, head, capacity, unitCost);
  }
  add_arcs_with_capacity_and_unit_cost(tails, heads, capacities, unitCosts) {
    let tailValues = toNumberArray(tails, "tails"), headValues = toNumberArray(heads, "heads"), capacityValues = toNumberArray(capacities, "capacities"), unitCostValues = toNumberArray(unitCosts, "unitCosts");
    return assertEqualLengths("SimpleMinCostFlow.add_arcs_with_capacity_and_unit_cost", tailValues, headValues, capacityValues, unitCostValues), tailValues.map((tail, index) => this.add_arc_with_capacity_and_unit_cost(tail, headValues[index], capacityValues[index], unitCostValues[index]));
  }
  addArcsWithCapacityAndUnitCost(tails, heads, capacities, unitCosts) {
    return this.add_arcs_with_capacity_and_unit_cost(tails, heads, capacities, unitCosts);
  }
  set_arc_capacity(arc, capacity) {
    assertIndex(arc, this.capacities.length, "arc"), this.capacities[arc] = toNumberArray([capacity], "capacity")[0], this.result = null;
  }
  setArcCapacity(arc, capacity) {
    this.set_arc_capacity(arc, capacity);
  }
  set_arc_capacities(arcs, capacities) {
    let arcValues = toNumberArray(arcs, "arcs"), capacityValues = toNumberArray(capacities, "capacities");
    assertEqualLengths("SimpleMinCostFlow.set_arc_capacities", arcValues, capacityValues);
    for (let [index, arc] of arcValues.entries()) this.set_arc_capacity(arc, capacityValues[index]);
  }
  setArcCapacities(arcs, capacities) {
    this.set_arc_capacities(arcs, capacities);
  }
  set_node_supply(node, supply) {
    let nodeValue = toNumberArray([node], "node")[0];
    for (; this.nodeSupplies.length <= nodeValue; ) this.nodeSupplies.push(0);
    this.nodeSupplies[nodeValue] = toNumberArray([supply], "supply")[0], this.result = null;
  }
  setNodeSupply(node, supply) {
    this.set_node_supply(node, supply);
  }
  set_nodes_supplies(nodes, supplies) {
    let nodeValues = toNumberArray(nodes, "nodes"), supplyValues = toNumberArray(supplies, "supplies");
    assertEqualLengths("SimpleMinCostFlow.set_nodes_supplies", nodeValues, supplyValues);
    for (let [index, node] of nodeValues.entries()) this.set_node_supply(node, supplyValues[index]);
  }
  setNodesSupplies(nodes, supplies) {
    this.set_nodes_supplies(nodes, supplies);
  }
  num_nodes() {
    return Math.max(
      this.nodeSupplies.length,
      this.tails.reduce((maxNode, tail, index) => Math.max(maxNode, tail, this.heads[index]), -1) + 1
    );
  }
  numNodes() {
    return this.num_nodes();
  }
  num_arcs() {
    return this.tails.length;
  }
  numArcs() {
    return this.num_arcs();
  }
  tail(arc) {
    return assertIndex(arc, this.tails.length, "arc"), this.tails[arc];
  }
  head(arc) {
    return assertIndex(arc, this.heads.length, "arc"), this.heads[arc];
  }
  capacity(arc) {
    return assertIndex(arc, this.capacities.length, "arc"), this.capacities[arc];
  }
  supply(node) {
    return assertIndex(node, this.num_nodes(), "node"), this.nodeSupplies[node] ?? 0;
  }
  unit_cost(arc) {
    return assertIndex(arc, this.unitCosts.length, "arc"), this.unitCosts[arc];
  }
  unitCost(arc) {
    return this.unit_cost(arc);
  }
  async solve() {
    let result = await solveGraphPayload({
      algorithm: "minCostFlow",
      tails: this.tails,
      heads: this.heads,
      capacities: this.capacities,
      unitCosts: this.unitCosts,
      supplies: this.nodeSupplies,
      solveMaxFlowWithMinCost: !1
    });
    return this.result = result, result.status;
  }
  async solve_max_flow_with_min_cost() {
    let result = await solveGraphPayload({
      algorithm: "minCostFlow",
      tails: this.tails,
      heads: this.heads,
      capacities: this.capacities,
      unitCosts: this.unitCosts,
      supplies: this.nodeSupplies,
      solveMaxFlowWithMinCost: !0
    });
    return this.result = result, result.status;
  }
  solveMaxFlowWithMinCost() {
    return this.solve_max_flow_with_min_cost();
  }
  optimal_cost() {
    return this.result?.optimalCost ?? 0;
  }
  optimalCost() {
    return this.optimal_cost();
  }
  maximum_flow() {
    return this.result?.maximumFlow ?? 0;
  }
  maximumFlow() {
    return this.maximum_flow();
  }
  flow(arc) {
    return assertIndex(arc, this.capacities.length, "arc"), this.result?.flows?.[arc] ?? 0;
  }
  flows(arcs) {
    return toNumberArray(arcs, "arcs").map((arc) => this.flow(arc));
  }
};
__publicField(SimpleMinCostFlow, "NOT_SOLVED", 0 /* NOT_SOLVED */), __publicField(SimpleMinCostFlow, "OPTIMAL", 1 /* OPTIMAL */), __publicField(SimpleMinCostFlow, "FEASIBLE", 2 /* FEASIBLE */), __publicField(SimpleMinCostFlow, "INFEASIBLE", 3 /* INFEASIBLE */), __publicField(SimpleMinCostFlow, "UNBALANCED", 4 /* UNBALANCED */), __publicField(SimpleMinCostFlow, "BAD_RESULT", 5 /* BAD_RESULT */), __publicField(SimpleMinCostFlow, "BAD_COST_RANGE", 6 /* BAD_COST_RANGE */), __publicField(SimpleMinCostFlow, "BAD_CAPACITY_RANGE", 7 /* BAD_CAPACITY_RANGE */);
var SimpleLinearSumAssignment = class {
  constructor() {
    __publicField(this, "leftNodes", []);
    __publicField(this, "rightNodes", []);
    __publicField(this, "costs", []);
    __publicField(this, "result", null);
  }
  add_arc_with_cost(leftNode, rightNode, cost) {
    let arc = this.leftNodes.length;
    return this.leftNodes.push(...toNumberArray([leftNode], "leftNode")), this.rightNodes.push(...toNumberArray([rightNode], "rightNode")), this.costs.push(...toNumberArray([cost], "cost")), this.result = null, arc;
  }
  addArcWithCost(leftNode, rightNode, cost) {
    return this.add_arc_with_cost(leftNode, rightNode, cost);
  }
  add_arcs_with_cost(leftNodes, rightNodes, costs) {
    let leftValues = toNumberArray(leftNodes, "leftNodes"), rightValues = toNumberArray(rightNodes, "rightNodes"), costValues = toNumberArray(costs, "costs");
    return assertEqualLengths("SimpleLinearSumAssignment.add_arcs_with_cost", leftValues, rightValues, costValues), leftValues.map((leftNode, index) => this.add_arc_with_cost(leftNode, rightValues[index], costValues[index]));
  }
  addArcsWithCost(leftNodes, rightNodes, costs) {
    return this.add_arcs_with_cost(leftNodes, rightNodes, costs);
  }
  num_nodes() {
    return this.leftNodes.reduce((maxNode, leftNode, index) => Math.max(maxNode, leftNode, this.rightNodes[index]), -1) + 1;
  }
  numNodes() {
    return this.num_nodes();
  }
  num_arcs() {
    return this.leftNodes.length;
  }
  numArcs() {
    return this.num_arcs();
  }
  left_node(arc) {
    return assertIndex(arc, this.leftNodes.length, "arc"), this.leftNodes[arc];
  }
  leftNode(arc) {
    return this.left_node(arc);
  }
  right_node(arc) {
    return assertIndex(arc, this.rightNodes.length, "arc"), this.rightNodes[arc];
  }
  rightNode(arc) {
    return this.right_node(arc);
  }
  cost(arc) {
    return assertIndex(arc, this.costs.length, "arc"), this.costs[arc];
  }
  async solve() {
    let result = await solveGraphPayload({
      algorithm: "linearSumAssignment",
      leftNodes: this.leftNodes,
      rightNodes: this.rightNodes,
      costs: this.costs
    });
    return this.result = result, result.status;
  }
  optimal_cost() {
    return this.result?.optimalCost ?? 0;
  }
  optimalCost() {
    return this.optimal_cost();
  }
  right_mate(leftNode) {
    return assertIndex(leftNode, this.num_nodes(), "leftNode"), this.result?.rightMates?.[leftNode] ?? -1;
  }
  rightMate(leftNode) {
    return this.right_mate(leftNode);
  }
  assignment_cost(leftNode) {
    return assertIndex(leftNode, this.num_nodes(), "leftNode"), this.result?.assignmentCosts?.[leftNode] ?? 0;
  }
  assignmentCost(leftNode) {
    return this.assignment_cost(leftNode);
  }
};
__publicField(SimpleLinearSumAssignment, "OPTIMAL", 0 /* OPTIMAL */), __publicField(SimpleLinearSumAssignment, "INFEASIBLE", 1 /* INFEASIBLE */), __publicField(SimpleLinearSumAssignment, "POSSIBLE_OVERFLOW", 2 /* POSSIBLE_OVERFLOW */);
var NetworkFlow = {
  initNetworkFlow,
  isWorkerBridgeEnabled,
  setWorkerBridgeEnabled,
  SimpleMaxFlow,
  SimpleMinCostFlow,
  SimpleLinearSumAssignment,
  SimpleMaxFlowStatus,
  SimpleMinCostFlowStatus,
  SimpleLinearSumAssignmentStatus
};

// ../javascript/lib/network-flow.ts
import {
  isWorkerBridgeAvailable,
  isWorkerBridgeEnabled as isWorkerBridgeEnabled2,
  setWorkerBridgeEnabled as setWorkerBridgeEnabled2,
  terminateWorkerBridge
} from "./worker_bridge.js";
import { terminateLoadedRuntimeThreads } from "./runtime_loader.js";
export {
  NetworkFlow,
  SimpleLinearSumAssignment,
  SimpleLinearSumAssignmentStatus,
  SimpleMaxFlow,
  SimpleMaxFlowStatus,
  SimpleMinCostFlow,
  SimpleMinCostFlowStatus,
  initNetworkFlow as init,
  initNetworkFlow,
  isWorkerBridgeAvailable,
  isWorkerBridgeEnabled2 as isWorkerBridgeEnabled,
  setWorkerBridgeEnabled2 as setWorkerBridgeEnabled,
  solveGraphPayload,
  terminateLoadedRuntimeThreads,
  terminateWorkerBridge
};
