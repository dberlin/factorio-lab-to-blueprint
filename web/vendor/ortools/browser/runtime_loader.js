import {
  createRuntimeLoader,
  isJspiSupported
} from "./runtime_loader_core.js";
const runtimeAssets = {
  cp_sat_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/cp_sat_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/cp_sat_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/cp_sat_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/cp_sat_runtime_asyncify.wasm", import.meta.url).href
    }
  },
  routing_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/routing_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/routing_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/routing_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/routing_runtime_asyncify.wasm", import.meta.url).href
    }
  },
  mp_solver_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/mp_solver_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/mp_solver_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/mp_solver_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/mp_solver_runtime_asyncify.wasm", import.meta.url).href
    }
  },
  mathopt_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/mathopt_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/mathopt_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/mathopt_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/mathopt_runtime_asyncify.wasm", import.meta.url).href
    }
  },
  pdlp_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/pdlp_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/pdlp_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/pdlp_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/pdlp_runtime_asyncify.wasm", import.meta.url).href
    }
  },
  graph_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/graph_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/graph_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/graph_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/graph_runtime_asyncify.wasm", import.meta.url).href
    }
  },
  set_cover_runtime: {
    jspi: {
      jsUrl: new URL("../wasm/set_cover_runtime.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/set_cover_runtime.wasm", import.meta.url).href
    },
    asyncify: {
      jsUrl: new URL("../wasm/set_cover_runtime_asyncify.js", import.meta.url).href,
      wasmUrl: new URL("../wasm/set_cover_runtime_asyncify.wasm", import.meta.url).href
    }
  }
};
async function loadFactory(runtimeUrl) {
  const { default: createModule } = await import(
    /* webpackIgnore: true */
    /* @vite-ignore */
    runtimeUrl
  );
  return createModule;
}
function runtimeAssetName(url) {
  return (new URL(url).pathname.split("/").pop() ?? "").replace(/-[A-Za-z0-9_-]+(?=\.(?:js|wasm)$)/, "");
}
function locateRuntimeFile(fileName) {
  for (const flavors of Object.values(runtimeAssets))
    for (const asset of Object.values(flavors)) {
      if (fileName === runtimeAssetName(asset.jsUrl)) return asset.jsUrl;
      if (fileName === runtimeAssetName(asset.wasmUrl)) return asset.wasmUrl;
    }
  return fileName;
}
const loader = createRuntimeLoader({
  logFlavorSelection: !0,
  loadFactory,
  async resolveAsset(runtimeName, flavor) {
    const asset = runtimeAssets[runtimeName][flavor], wasmBinary = new Uint8Array(await (await fetch(asset.wasmUrl)).arrayBuffer());
    return {
      jsUrl: asset.jsUrl,
      locateFile: locateRuntimeFile,
      wasmBinary,
      mainScriptUrlOrBlob: asset.jsUrl
    };
  }
}), terminateLoadedRuntimeThreads = loader.terminateLoadedRuntimeThreads, loadRuntime = loader.loadRuntime, loadRuntimeAsyncify = loader.loadRuntimeAsyncify, loadRoutingRuntime = loader.loadRoutingRuntime, loadRoutingRuntimeAsyncify = loader.loadRoutingRuntimeAsyncify, loadMPSolverRuntime = loader.loadMPSolverRuntime, loadMPSolverRuntimeAsyncify = loader.loadMPSolverRuntimeAsyncify, loadMathOptRuntime = loader.loadMathOptRuntime, loadMathOptRuntimeAsyncify = loader.loadMathOptRuntimeAsyncify, loadPdlpRuntime = loader.loadPdlpRuntime, loadPdlpRuntimeAsyncify = loader.loadPdlpRuntimeAsyncify, loadGraphRuntime = loader.loadGraphRuntime, loadGraphRuntimeAsyncify = loader.loadGraphRuntimeAsyncify, loadSetCoverRuntime = loader.loadSetCoverRuntime, loadSetCoverRuntimeAsyncify = loader.loadSetCoverRuntimeAsyncify;
export {
  isJspiSupported,
  loadRuntime as loadCpSat,
  loadRuntimeAsyncify as loadCpSatAsyncify,
  loadGraphRuntime,
  loadGraphRuntimeAsyncify,
  loadMPSolverRuntime,
  loadMPSolverRuntimeAsyncify,
  loadMathOptRuntime,
  loadMathOptRuntimeAsyncify,
  loadPdlpRuntime,
  loadPdlpRuntimeAsyncify,
  loadRoutingRuntime,
  loadRoutingRuntimeAsyncify,
  loadRuntime,
  loadRuntimeAsyncify,
  loadSetCoverRuntime,
  loadSetCoverRuntimeAsyncify,
  terminateLoadedRuntimeThreads
};
