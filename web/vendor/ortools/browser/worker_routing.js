import { loadRoutingRuntime } from "./runtime_loader.js";
let modulePromise = null;
function toNumber(value) {
  return typeof value == "number" ? value : Number(value);
}
function toInt64(value) {
  return globalThis.BigInt(value);
}
function loadModule() {
  return modulePromise ?? (modulePromise = loadRoutingRuntime()), modulePromise;
}
function copyInt32Array(module, values) {
  const array = new Int32Array(values), ptr = module._malloc(array.byteLength);
  return module.HEAPU8.set(new Uint8Array(array.buffer), ptr), ptr;
}
function copyInt64Array(module, values) {
  const array = values instanceof BigInt64Array ? values : new BigInt64Array(values.map((value) => BigInt(value))), ptr = module._malloc(array.byteLength);
  return module.HEAPU8.set(new Uint8Array(array.buffer, array.byteOffset, array.byteLength), ptr), { ptr, length: array.length };
}
function copyString(module, value) {
  const bytes = new TextEncoder().encode(`${value}\0`), ptr = module._malloc(bytes.byteLength);
  return module.HEAPU8.set(bytes, ptr), ptr;
}
async function withStringAsync(module, value, fn) {
  const ptr = copyString(module, value);
  try {
    return await fn(ptr);
  } finally {
    module._free(ptr);
  }
}
async function ccallNumber(module, name, argTypes, args) {
  return await module.ccall(name, "number", argTypes, args, { async: !0 });
}
async function ccallBigInt(module, name, argTypes, args) {
  return await module.ccall(name, "bigint", argTypes, args, { async: !0 });
}
async function registerTransitMatrix(module, modelHandle, matrix, dimension) {
  const { ptr, length } = copyInt64Array(module, matrix);
  try {
    const evaluatorIndex = await ccallNumber(
      module,
      "routing_register_matrix_transit_callback",
      ["number", "number", "number", "number"],
      [modelHandle, ptr, length, dimension]
    );
    if (evaluatorIndex < 0)
      throw new Error("Routing worker failed to register transit matrix.");
    return evaluatorIndex;
  } finally {
    module._free(ptr);
  }
}
async function solveRoutingWithModule(module, message) {
  let managerHandle = 0, modelHandle = 0, startsPtr = 0, endsPtr = 0;
  {
    startsPtr = copyInt32Array(module, message.starts), endsPtr = copyInt32Array(module, message.ends), managerHandle = await ccallNumber(
      module,
      "routing_create_index_manager_starts_ends",
      ["number", "number", "number", "number"],
      [message.numLocations, message.numVehicles, startsPtr, endsPtr]
    ), modelHandle = await ccallNumber(module, "routing_create_model", ["number"], [managerHandle]);
    const evaluatorIndex = await registerTransitMatrix(module, modelHandle, message.transitMatrix, message.transitMatrixDimension);
    await ccallNumber(
      module,
      "routing_set_arc_cost_evaluator_of_all_vehicles",
      ["number", "number"],
      [modelHandle, evaluatorIndex]
    );
    for (const operation of message.operations)
      if (operation.type === "addDimension") {
        const index = await registerTransitMatrix(module, modelHandle, operation.transitMatrix, message.transitMatrixDimension);
        await withStringAsync(module, operation.name, async (namePtr) => {
          await ccallNumber(
            module,
            "routing_add_dimension",
            ["number", "number", "bigint", "bigint", "number", "number"],
            [modelHandle, index, BigInt(operation.slackMax), BigInt(operation.capacity), operation.fixStartCumulToZero ? 1 : 0, namePtr]
          );
        });
      } else if (operation.type === "addDimensionWithVehicleCapacity") {
        const index = await registerTransitMatrix(module, modelHandle, operation.transitMatrix, message.transitMatrixDimension), capacities = copyInt64Array(module, operation.capacities);
        try {
          await withStringAsync(module, operation.name, async (namePtr) => {
            await ccallNumber(
              module,
              "routing_add_dimension_with_vehicle_capacity",
              ["number", "number", "bigint", "number", "number", "number", "number"],
              [modelHandle, index, BigInt(operation.slackMax), capacities.ptr, capacities.length, operation.fixStartCumulToZero ? 1 : 0, namePtr]
            );
          });
        } finally {
          module._free(capacities.ptr);
        }
      } else if (operation.type === "addDimensionWithVehicleTransits") {
        const evaluatorIndices = [];
        for (const matrix of operation.transitMatrices)
          evaluatorIndices.push(await registerTransitMatrix(module, modelHandle, matrix, message.transitMatrixDimension));
        const evaluatorsPtr = copyInt32Array(module, evaluatorIndices);
        try {
          await withStringAsync(module, operation.name, async (namePtr) => {
            await ccallNumber(
              module,
              "routing_add_dimension_with_vehicle_transits",
              ["number", "number", "number", "bigint", "bigint", "number", "number"],
              [modelHandle, evaluatorsPtr, evaluatorIndices.length, BigInt(operation.slackMax), BigInt(operation.capacity), operation.fixStartCumulToZero ? 1 : 0, namePtr]
            );
          });
        } finally {
          module._free(evaluatorsPtr);
        }
      } else if (operation.type === "addConstantDimension")
        await withStringAsync(module, operation.name, async (namePtr) => {
          await ccallNumber(
            module,
            "routing_add_constant_dimension",
            ["number", "bigint", "bigint", "number", "number"],
            [modelHandle, BigInt(operation.value), BigInt(operation.capacity), operation.fixStartCumulToZero ? 1 : 0, namePtr]
          );
        });
      else if (operation.type === "addVectorDimension") {
        const values = copyInt64Array(module, operation.values);
        try {
          await withStringAsync(module, operation.name, async (namePtr) => {
            await ccallNumber(
              module,
              "routing_add_vector_dimension",
              ["number", "number", "number", "bigint", "number", "number"],
              [modelHandle, values.ptr, values.length, BigInt(operation.capacity), operation.fixStartCumulToZero ? 1 : 0, namePtr]
            );
          });
        } finally {
          module._free(values.ptr);
        }
      } else if (operation.type === "addMatrixDimension") {
        const flat = operation.matrix.flat(), matrix = copyInt64Array(module, flat);
        try {
          await withStringAsync(module, operation.name, async (namePtr) => {
            await ccallNumber(
              module,
              "routing_add_matrix_dimension",
              ["number", "number", "number", "number", "bigint", "number", "number"],
              [modelHandle, matrix.ptr, matrix.length, operation.matrix.length, BigInt(operation.capacity), operation.fixStartCumulToZero ? 1 : 0, namePtr]
            );
          });
        } finally {
          module._free(matrix.ptr);
        }
      } else if (operation.type === "addDisjunction") {
        const indices = copyInt64Array(module, operation.indices);
        try {
          await ccallNumber(
            module,
            "routing_add_disjunction",
            ["number", "number", "number", "bigint", "number"],
            [modelHandle, indices.ptr, indices.length, BigInt(operation.penalty ?? 0), operation.penalty === void 0 ? 0 : 1]
          );
        } finally {
          module._free(indices.ptr);
        }
      } else operation.type === "addPickupAndDelivery" && await ccallNumber(
        module,
        "routing_add_pickup_and_delivery",
        ["number", "bigint", "bigint"],
        [modelHandle, toInt64(operation.pickup), toInt64(operation.delivery)]
      );
    if (await ccallNumber(
      module,
      "routing_solve_with_parameters_ext",
      ["number", "number", "number"],
      [modelHandle, message.firstSolutionStrategy, message.solutionLimit]
    ) !== 1)
      return null;
    const starts = [], ends = [], nextValues = Array.from({ length: message.transitMatrixDimension }, (_, index) => index), dimensionCumulValues = {};
    for (let vehicle = 0; vehicle < message.numVehicles; vehicle++) {
      let index = toNumber(await ccallBigInt(module, "routing_start", ["number", "number"], [modelHandle, vehicle]));
      for (starts.push(index); await ccallNumber(module, "routing_is_end", ["number", "bigint"], [modelHandle, toInt64(index)]) !== 1; ) {
        const next = toNumber(await ccallBigInt(module, "routing_next_value", ["number", "bigint"], [modelHandle, toInt64(index)]));
        nextValues[index] = next, index = next;
      }
      ends.push(index);
    }
    for (const dimensionName of message.dimensionNames)
      dimensionCumulValues[dimensionName] = [], await withStringAsync(module, dimensionName, async (namePtr) => {
        for (let index = 0; index < message.transitMatrixDimension; index++)
          dimensionCumulValues[dimensionName][index] = toNumber(
            await ccallBigInt(
              module,
              "routing_assignment_dimension_cumul_value",
              ["number", "number", "bigint"],
              [modelHandle, namePtr, toInt64(index)]
            )
          );
      });
    return {
      status: await ccallNumber(module, "routing_status", ["number"], [modelHandle]),
      objectiveValue: toNumber(await ccallBigInt(module, "routing_assignment_objective_value", ["number"], [modelHandle])),
      nextValues,
      starts,
      ends,
      dimensionCumulValues
    };
  }
}
async function solveRoutingInWorker(message) {
  return await solveRoutingWithModule(await loadModule(), message);
}
export {
  solveRoutingInWorker
};
