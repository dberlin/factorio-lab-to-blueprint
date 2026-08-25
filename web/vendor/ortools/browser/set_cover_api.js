var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);
import { loadSetCoverRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
var ConsistencyLevel = /* @__PURE__ */ ((ConsistencyLevel2) => (ConsistencyLevel2[ConsistencyLevel2.COST_AND_COVERAGE = 1] = "COST_AND_COVERAGE", ConsistencyLevel2[ConsistencyLevel2.FREE_AND_UNCOVERED = 2] = "FREE_AND_UNCOVERED", ConsistencyLevel2[ConsistencyLevel2.REDUNDANCY = 3] = "REDUNDANCY", ConsistencyLevel2))(ConsistencyLevel || {});
const consistency_level = ConsistencyLevel, operationCode = {
  trivial: 0,
  greedy: 1,
  elementDegree: 2,
  lazyElementDegree: 3,
  random: 4,
  steepest: 5,
  guidedLocal: 6,
  guidedTabu: 7
};
let setCoverModulePromise = null, setCoverModule = null;
async function initSetCover() {
  shouldUseWorkerBridge() || (setCoverModulePromise ?? (setCoverModulePromise = loadSetCoverRuntime().then((module) => (setCoverModule = module, module))), await setCoverModulePromise);
}
function currentModule() {
  if (!setCoverModule)
    throw new Error("Set Cover runtime has not been initialized. Call initSetCover() first.");
  return setCoverModule;
}
function copyFloat64ToHeap(module, values) {
  if (!values.length) return 0;
  const ptr = module._malloc(values.length * Float64Array.BYTES_PER_ELEMENT);
  return new Float64Array(module.HEAPU8.buffer, ptr, values.length).set(values), ptr;
}
function boolsToNumbers(values) {
  return values.map((value) => value ? 1 : 0);
}
function parseNativeResult(serialized) {
  const result = JSON.parse(serialized);
  if (!result.ok)
    throw new Error(result.error || "SetCover: native operation failed.");
  return result;
}
function assertSubsetIndex(index, numSubsets, label = "subset") {
  if (!Number.isInteger(index) || index < 0 || index >= numSubsets)
    throw new Error(`SetCover: ${label} ${index} is out of range.`);
}
function createSolutionResponse(subsets, cost, numSubsets) {
  return {
    status: 2,
    numSubsets,
    subset: [...subsets],
    cost,
    toString() {
      return JSON.stringify({
        status: this.status,
        numSubsets: this.numSubsets,
        subset: this.subset,
        cost: this.cost
      });
    }
  };
}
function stats(values) {
  if (!values.length)
    return new SetCoverModelStats(0, 0, 0, 0, 0);
  const sorted = [...values].sort((a, b) => a - b), mean = sorted.reduce((sum, value) => sum + value, 0) / sorted.length, variance = sorted.reduce((sum, value) => sum + (value - mean) ** 2, 0) / sorted.length;
  return new SetCoverModelStats(
    sorted[0],
    sorted[sorted.length - 1],
    sorted[Math.floor(sorted.length / 2)],
    mean,
    Math.sqrt(variance)
  );
}
function deciles(values) {
  if (!values.length) return [];
  const sorted = [...values].sort((a, b) => a - b);
  return Array.from({ length: 11 }, (_, index) => sorted[Math.min(sorted.length - 1, Math.floor(index * (sorted.length - 1) / 10))]);
}
async function runNativeSetCover(payload) {
  if (shouldUseWorkerBridge()) {
    const response = await postWorkerRequest({
      type: "setCover",
      id: nextWorkerBridgeRequestId(),
      ...payload
    });
    return parseNativeResult(response.result);
  }
  await initSetCover();
  const module = currentModule(), costsPtr = copyFloat64ToHeap(module, payload.costs), startsPtr = copyFloat64ToHeap(module, payload.starts), elementsPtr = copyFloat64ToHeap(module, payload.elements), selectedPtr = copyFloat64ToHeap(module, boolsToNumbers(payload.selected)), focusPtr = payload.focus ? copyFloat64ToHeap(module, boolsToNumbers(payload.focus)) : 0;
  try {
    return parseNativeResult(await module.ccall(
      "set_cover_next_solution_serialized",
      "string",
      ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
      [
        costsPtr,
        startsPtr,
        elementsPtr,
        payload.costs.length,
        payload.elements.length,
        selectedPtr,
        focusPtr,
        operationCode[payload.operation],
        payload.maxIterations
      ],
      { async: !0 }
    ));
  } finally {
    costsPtr && module._free(costsPtr), startsPtr && module._free(startsPtr), elementsPtr && module._free(elementsPtr), selectedPtr && module._free(selectedPtr), focusPtr && module._free(focusPtr);
  }
}
class SetCoverModelStats {
  constructor(min, max, median, mean, stddev) {
    __publicField(this, "min", min);
    __publicField(this, "max", max);
    __publicField(this, "median", median);
    __publicField(this, "mean", mean);
    __publicField(this, "stddev", stddev);
  }
  get to_string() {
    return `${this.min}, ${this.max}, ${this.median}, ${this.mean}, ${this.stddev}`;
  }
  get to_verbose_string() {
    return `min: ${this.min}, max: ${this.max}, median: ${this.median}, mean: ${this.mean}, stddev: ${this.stddev}`;
  }
}
class SetCoverModel {
  constructor() {
    __publicField(this, "modelName", "SetCoverModel");
    __publicField(this, "costs", []);
    __publicField(this, "subsetElements", []);
    __publicField(this, "rowElements", []);
    __publicField(this, "validRows", !1);
  }
  get name() {
    return this.modelName;
  }
  get num_elements() {
    let max = -1;
    for (const subset of this.subsetElements)
      for (const element of subset) max = Math.max(max, element);
    return max + 1;
  }
  get num_subsets() {
    return this.subsetElements.length;
  }
  get num_nonzeros() {
    return this.subsetElements.reduce((sum, subset) => sum + subset.length, 0);
  }
  get fill_rate() {
    const denominator = this.num_elements * this.num_subsets;
    return denominator === 0 ? 0 : this.num_nonzeros / denominator;
  }
  get subset_costs() {
    return [...this.costs];
  }
  get columns() {
    return this.subsetElements.map((subset) => [...subset]);
  }
  get rows() {
    return this.validRows || this.create_sparse_row_view(), this.rowElements.map((row) => [...row]);
  }
  get row_view_is_valid() {
    return this.validRows;
  }
  get all_subsets() {
    return this.SubsetRange();
  }
  SubsetRange() {
    return Array.from({ length: this.num_subsets }, (_, index) => index);
  }
  ElementRange() {
    return Array.from({ length: this.num_elements }, (_, index) => index);
  }
  set_name(name) {
    this.modelName = name;
  }
  add_empty_subset(cost) {
    if (!Number.isFinite(cost)) throw new Error("SetCoverModel.add_empty_subset: cost must be finite.");
    this.costs.push(cost), this.subsetElements.push([]), this.validRows = !1;
  }
  add_element_to_last_subset(element) {
    if (!this.subsetElements.length)
      throw new Error("SetCoverModel.add_element_to_last_subset: no subset exists.");
    this.add_element_to_subset(element, this.subsetElements.length - 1);
  }
  set_subset_cost(subset, cost) {
    if (assertSubsetIndex(subset, this.num_subsets), !Number.isFinite(cost)) throw new Error("SetCoverModel.set_subset_cost: cost must be finite.");
    this.costs[subset] = cost;
  }
  add_element_to_subset(element, subset) {
    if (assertSubsetIndex(subset, this.num_subsets), !Number.isInteger(element) || element < 0)
      throw new Error("SetCoverModel.add_element_to_subset: element must be a non-negative integer.");
    this.subsetElements[subset].push(element), this.validRows = !1;
  }
  create_sparse_row_view() {
    this.rowElements = Array.from({ length: this.num_elements }, () => []), this.subsetElements.forEach((subset, subsetIndex) => {
      for (const element of subset)
        this.rowElements[element]?.push(subsetIndex);
    }), this.rowElements.forEach((row) => row.sort((a, b) => a - b)), this.validRows = !0;
  }
  sort_elements_in_subsets() {
    this.subsetElements.forEach((subset) => subset.sort((a, b) => a - b)), this.validRows = !1;
  }
  compute_feasibility() {
    const covered = /* @__PURE__ */ new Set();
    for (const subset of this.subsetElements)
      for (const element of subset) covered.add(element);
    for (let element = 0; element < this.num_elements; element++)
      if (!covered.has(element)) return !1;
    return this.num_elements > 0 || this.num_subsets > 0;
  }
  resize_num_subsets(numSubsets) {
    for (; this.num_subsets < numSubsets; ) this.add_empty_subset(0);
  }
  reserve_num_elements_in_subset(_numElements, subset) {
    assertSubsetIndex(subset, this.num_subsets);
  }
  export_model_as_proto() {
    return {
      name: this.modelName,
      subset: this.subsetElements.map((element, index) => ({ cost: this.costs[index], element: [...element].sort((a, b) => a - b) }))
    };
  }
  import_model_from_proto(proto) {
    this.modelName = proto.name ?? "SetCoverModel", this.costs = proto.subset.map((subset) => subset.cost ?? 0), this.subsetElements = proto.subset.map((subset) => [...subset.element ?? []]), this.validRows = !1;
  }
  compute_cost_stats() {
    return stats(this.costs);
  }
  compute_row_stats() {
    return stats(this.rows.map((row) => row.length));
  }
  compute_column_stats() {
    return stats(this.subsetElements.map((subset) => subset.length));
  }
  compute_row_deciles() {
    return deciles(this.rows.map((row) => row.length));
  }
  compute_column_deciles() {
    return deciles(this.subsetElements.map((subset) => subset.length));
  }
  _nativePayload(selected, focus, operation, maxIterations) {
    const starts = [0], elements = [];
    for (const subset of this.subsetElements)
      elements.push(...subset), starts.push(elements.length);
    return {
      operation,
      costs: [...this.costs],
      starts,
      elements,
      selected,
      focus,
      maxIterations
    };
  }
}
class SetCoverDecision {
  constructor(subsetIndex = 0, decisionValue = !0) {
    __publicField(this, "subsetIndex", subsetIndex);
    __publicField(this, "decisionValue", decisionValue);
  }
  subset() {
    return this.subsetIndex;
  }
  decision() {
    return this.decisionValue;
  }
}
class SetCoverInvariant {
  constructor(currentModel) {
    __publicField(this, "currentModel", currentModel);
    __publicField(this, "selected", []);
    __publicField(this, "solutionTrace", []);
    __publicField(this, "currentCost", 0);
    __publicField(this, "currentCoverage", []);
    __publicField(this, "freeElements", []);
    __publicField(this, "coverageLe1Elements", []);
    __publicField(this, "redundant", []);
    __publicField(this, "uncoveredElements", 0);
    this.initialize();
  }
  initialize() {
    this.selected = Array.from({ length: this.currentModel.num_subsets }, () => !1), this.solutionTrace = [], this.recompute();
  }
  clear() {
    this.initialize();
  }
  model() {
    return this.currentModel;
  }
  get model_property() {
    return this.currentModel;
  }
  set model_property(model) {
    this.currentModel = model, this.initialize();
  }
  cost() {
    return this.currentCost;
  }
  num_uncovered_elements() {
    return this.uncoveredElements;
  }
  is_selected() {
    return [...this.selected];
  }
  num_free_elements() {
    return [...this.freeElements];
  }
  num_coverage_le_1_elements() {
    return [...this.coverageLe1Elements];
  }
  coverage() {
    return [...this.currentCoverage];
  }
  compute_coverage_in_focus(focus) {
    const coverage = Array.from({ length: this.currentModel.num_elements }, () => 0), columns = this.currentModel.columns;
    for (const subset of focus) {
      assertSubsetIndex(subset, this.currentModel.num_subsets);
      for (const element of columns[subset]) coverage[element]++;
    }
    return coverage;
  }
  is_redundant() {
    return [...this.redundant];
  }
  trace() {
    return [...this.solutionTrace];
  }
  clear_trace() {
    this.solutionTrace = [];
  }
  clear_removability_information() {
  }
  newly_removable_subsets() {
    return [];
  }
  newly_non_removable_subsets() {
    return [];
  }
  compress_trace() {
    this.solutionTrace = this.selected.map((value, subset) => value ? new SetCoverDecision(subset, !0) : null).filter((value) => value !== null);
  }
  load_solution(solution) {
    if (solution.length !== this.currentModel.num_subsets)
      throw new Error("SetCoverInvariant.load_solution: solution length must match num_subsets.");
    this.selected = [...solution], this.solutionTrace = solution.map((value, subset) => value ? new SetCoverDecision(subset, !0) : null).filter((value) => value !== null), this.recompute();
  }
  check_consistency(_consistency) {
    return this.recompute(), this.currentCoverage.length === this.currentModel.num_elements && this.selected.length === this.currentModel.num_subsets;
  }
  compute_is_redundant(subset) {
    return assertSubsetIndex(subset, this.currentModel.num_subsets), this.currentModel.columns[subset].every((element) => this.currentCoverage[element] > 1);
  }
  recompute() {
    const columns = this.currentModel.columns, costs = this.currentModel.subset_costs;
    this.currentCoverage = Array.from({ length: this.currentModel.num_elements }, () => 0), this.currentCost = 0, this.selected.forEach((value, subset) => {
      if (value) {
        this.currentCost += costs[subset] ?? 0;
        for (const element of columns[subset] ?? []) this.currentCoverage[element]++;
      }
    }), this.uncoveredElements = this.currentCoverage.filter((value) => value === 0).length, this.freeElements = columns.map((subset) => subset.filter((element) => this.currentCoverage[element] === 0).length), this.coverageLe1Elements = columns.map((subset) => subset.filter((element) => this.currentCoverage[element] <= 1).length), this.redundant = columns.map((subset) => subset.every((element) => this.currentCoverage[element] > 1));
  }
  select(subset, _consistency) {
    return assertSubsetIndex(subset, this.currentModel.num_subsets), this.selected[subset] ? !1 : (this.selected[subset] = !0, this.solutionTrace.push(new SetCoverDecision(subset, !0)), this.recompute(), !0);
  }
  deselect(subset, _consistency) {
    return assertSubsetIndex(subset, this.currentModel.num_subsets), this.selected[subset] ? (this.selected[subset] = !1, this.solutionTrace.push(new SetCoverDecision(subset, !1)), this.recompute(), !0) : !1;
  }
  export_solution_as_proto() {
    const subsets = this.selected.flatMap((value, subset) => value ? [subset] : []);
    return createSolutionResponse(subsets, this.currentCost, this.currentModel.num_subsets);
  }
  import_solution_from_proto(proto) {
    const selected = Array.from({ length: this.currentModel.num_subsets }, () => !1);
    for (const subset of proto.subset ?? [])
      assertSubsetIndex(subset, this.currentModel.num_subsets), selected[subset] = !0;
    this.load_solution(selected);
  }
  _applyNativeResult(result) {
    this.selected = [...result.selected], this.currentCost = result.cost, this.uncoveredElements = result.numUncoveredElements, this.currentCoverage = [...result.coverage], this.freeElements = [...result.numFreeElements], this.coverageLe1Elements = [...result.numCoverageLe1Elements], this.redundant = [...result.isRedundant], this.compress_trace();
  }
  _nativeSelected() {
    return [...this.selected];
  }
}
class SetCoverSolutionGenerator {
  constructor(invariant, operation, generatorName) {
    __publicField(this, "invariant", invariant);
    __publicField(this, "operation", operation);
    __publicField(this, "generatorName", generatorName);
    __publicField(this, "maxIterations", Number.POSITIVE_INFINITY);
  }
  set_max_iterations(maxIterations) {
    this.maxIterations = maxIterations;
  }
  async next_solution(focus) {
    const model = this.invariant.model();
    let focusMask = null;
    if (Array.isArray(focus))
      if (focus.every((value) => typeof value == "boolean"))
        focusMask = [...focus];
      else {
        focusMask = Array.from({ length: model.num_subsets }, () => !1);
        for (const subset of focus)
          assertSubsetIndex(subset, model.num_subsets), focusMask[subset] = !0;
      }
    const result = await runNativeSetCover(model._nativePayload(
      this.invariant._nativeSelected(),
      focusMask,
      this.operation,
      this.maxIterations
    ));
    return this.invariant._applyNativeResult(result), result.nextSolution;
  }
  name() {
    return this.generatorName;
  }
}
class TrivialSolutionGenerator extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "trivial", "TrivialGenerator");
  }
}
class RandomSolutionGenerator extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "random", "RandomGenerator");
  }
}
class GreedySolutionGenerator extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "greedy", "GreedyGenerator");
  }
}
class ElementDegreeSolutionGenerator extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "elementDegree", "ElementDegreeGenerator");
  }
}
class LazyElementDegreeSolutionGenerator extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "lazyElementDegree", "LazyElementDegreeGenerator");
  }
}
class SteepestSearch extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "steepest", "SteepestSearch");
  }
}
class GuidedLocalSearch extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "guidedLocal", "GuidedLocalSearch");
  }
  initialize() {
  }
}
class TabuList {
  constructor(listSize) {
    __publicField(this, "listSize", listSize);
    __publicField(this, "values", []);
    __publicField(this, "index", 0);
    this.init(listSize);
  }
  size() {
    return this.listSize;
  }
  init(size) {
    this.listSize = size, this.values = [], this.index = 0;
  }
  add(value) {
    if (this.values.length < this.listSize) {
      this.values.push(value);
      return;
    }
    this.values[this.index] = value, this.index = (this.index + 1) % Math.max(1, this.listSize);
  }
  contains(value) {
    return this.values.includes(value);
  }
}
class GuidedTabuSearch extends SetCoverSolutionGenerator {
  constructor(invariant) {
    super(invariant, "guidedTabu", "GuidedTabuSearch");
    __publicField(this, "lagrangianFactor", 100);
    __publicField(this, "epsilon", 1e-6);
    __publicField(this, "penaltyFactor", 0.3);
    __publicField(this, "tabuListSize", 17);
  }
  initialize() {
  }
  set_lagrangian_factor(factor) {
    this.lagrangianFactor = factor;
  }
  get_lagrangian_factor() {
    return this.lagrangianFactor;
  }
  set_epsilon(value) {
    this.epsilon = value;
  }
  get_epsilon() {
    return this.epsilon;
  }
  set_penalty_factor(factor) {
    this.penaltyFactor = factor;
  }
  get_penalty_factor() {
    return this.penaltyFactor;
  }
  set_tabu_list_size(size) {
    this.tabuListSize = size;
  }
  get_tabu_list_size() {
    return this.tabuListSize;
  }
}
function clear_random_subsets(numSubsetsOrFocus, invariantOrNumSubsets, maybeInvariant) {
  const invariant = typeof numSubsetsOrFocus == "number" ? invariantOrNumSubsets : maybeInvariant, numSubsets = typeof numSubsetsOrFocus == "number" ? numSubsetsOrFocus : invariantOrNumSubsets;
  if (!invariant) throw new Error("clear_random_subsets: invariant is required.");
  const selected = invariant.is_selected(), chosen = [];
  for (let subset = 0; subset < selected.length && chosen.length < numSubsets; subset++)
    selected[subset] && (invariant.deselect(subset, 1 /* COST_AND_COVERAGE */), chosen.push(subset));
  return chosen;
}
const clear_most_covered_elements = clear_random_subsets;
function read_set_cover_proto(_filename, _binary) {
  throw new Error("read_set_cover_proto is not available in the browser-oriented wasm runtime. Use import_model_from_proto().");
}
function write_set_cover_proto(_model, _filename, _binary) {
  throw new Error("write_set_cover_proto is not available in the browser-oriented wasm runtime. Use export_model_as_proto().");
}
function read_set_cover_solution_proto(_filename, _binary) {
  throw new Error("read_set_cover_solution_proto is not available in the browser-oriented wasm runtime. Use import_solution_from_proto().");
}
function write_set_cover_solution_proto(_model, _solution, _filename, _binary) {
  throw new Error("write_set_cover_solution_proto is not available in the browser-oriented wasm runtime. Use export_solution_as_proto().");
}
const read_orlib_scp = read_set_cover_proto, read_orlib_rail = read_set_cover_proto, read_fimi_dat = read_set_cover_proto, write_orlib_scp = write_set_cover_proto, write_orlib_rail = write_set_cover_proto, write_set_cover_solution_text = write_set_cover_solution_proto, read_set_cover_solution_text = read_set_cover_solution_proto;
export {
  ConsistencyLevel,
  ElementDegreeSolutionGenerator,
  GreedySolutionGenerator,
  GuidedLocalSearch,
  GuidedTabuSearch,
  LazyElementDegreeSolutionGenerator,
  RandomSolutionGenerator,
  SetCoverDecision,
  SetCoverInvariant,
  SetCoverModel,
  SetCoverModelStats,
  SteepestSearch,
  TabuList,
  TrivialSolutionGenerator,
  clear_most_covered_elements,
  clear_random_subsets,
  consistency_level,
  initSetCover,
  isWorkerBridgeEnabled,
  read_fimi_dat,
  read_orlib_rail,
  read_orlib_scp,
  read_set_cover_proto,
  read_set_cover_solution_proto,
  read_set_cover_solution_text,
  setWorkerBridgeEnabled,
  write_orlib_rail,
  write_orlib_scp,
  write_set_cover_proto,
  write_set_cover_solution_proto,
  write_set_cover_solution_text
};
