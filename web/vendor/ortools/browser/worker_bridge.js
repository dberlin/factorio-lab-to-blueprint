const isPackagedBrowserBuild = !0, isBrowserMainThread = typeof window < "u" && typeof document < "u", isDeno = "Deno" in globalThis, isBun = "Bun" in globalThis, isNode = typeof process < "u" && typeof process.versions?.node == "string" && !isDeno && !isBun, workerBridgeAvailable = (isBrowserMainThread || isDeno || isBun) && typeof Worker < "u" || isNode;
let worker = null, workerReadyPromise = null, workerBridgePreferred = isBrowserMainThread && workerBridgeAvailable, nextRequestId = 1;
const pendingWorkerRequests = /* @__PURE__ */ new Map();
function shouldUseWorkerBridge() {
  return workerBridgePreferred && workerBridgeAvailable;
}
function isWorkerBridgeEnabled() {
  return shouldUseWorkerBridge();
}
function isWorkerBridgeAvailable() {
  return workerBridgeAvailable;
}
function setWorkerBridgeEnabled(enabled) {
  if (workerBridgePreferred = !!enabled, workerBridgePreferred && !workerBridgeAvailable)
    throw workerBridgePreferred = !1, new Error("Worker bridge requested but no worker is available in this environment.");
  workerBridgePreferred || terminateWorkerBridge("OR-Tools worker bridge disabled.");
}
function nextWorkerBridgeRequestId() {
  return nextRequestId++;
}
function terminateWorkerBridge(reason) {
  if (!worker) return;
  worker.terminate(), worker = null, workerReadyPromise = null;
  const error = new Error(reason ?? "OR-Tools worker terminated.");
  for (const pending of pendingWorkerRequests.values())
    pending.reject(error);
  pendingWorkerRequests.clear();
}
async function createBridgeWorker() {
  return new Worker(new URL("./ortools_worker.js", import.meta.url), { type: "module" });
}
async function ensureWorker() {
  if (!workerBridgeAvailable)
    throw new Error("Worker bridge is not available.");
  if (worker)
    return worker;
  const instance = await createBridgeWorker();
  return instance.unref?.(), worker = instance, workerReadyPromise = new Promise((resolve, reject) => {
    const handleMessage = (message) => {
      if (message.type === "ready") {
        resolve();
        return;
      }
      const pending = pendingWorkerRequests.get(message.id);
      if (message.type === "solveCallback") {
        if (pending?.onEvent)
          try {
            pending.onEvent(message);
          } catch (error) {
            pendingWorkerRequests.delete(message.id), pending.reject(error);
          }
        return;
      }
      if (message.type === "error") {
        const error = new Error(message.error);
        pending ? (pending.reject(error), pendingWorkerRequests.delete(message.id)) : reject(error);
        return;
      }
      pending && (pendingWorkerRequests.delete(message.id), pending.resolve(message));
    }, handleError = (errorLike) => {
      const detail = errorLike instanceof Error ? errorLike.message : errorLike.error instanceof Error ? errorLike.error.message : errorLike.message || "The runtime blocked or failed to load the worker module.", error = new Error(`OR-Tools worker failed to load: ${detail}`);
      reject(error), terminateWorkerBridge(error.message);
    };
    typeof instance.on == "function" ? (instance.on("message", handleMessage), instance.on("error", handleError)) : (instance.onmessage = (event) => handleMessage(event.data), instance.onerror = handleError);
  }), instance;
}
async function waitForWorkerReady() {
  if (!workerBridgeAvailable)
    throw new Error("Worker bridge is not available.");
  if (await ensureWorker(), !workerReadyPromise)
    throw new Error("Worker ready state unavailable.");
  await workerReadyPromise;
}
async function postWorkerRequest(request, onEvent) {
  if (!workerBridgeAvailable)
    throw new Error("Worker bridge is not available.");
  const workerInstance = await ensureWorker();
  return await waitForWorkerReady(), new Promise((resolve, reject) => {
    pendingWorkerRequests.set(request.id, {
      resolve: (value) => resolve(value),
      reject,
      onEvent
    }), workerInstance.postMessage(request);
  });
}
export {
  isWorkerBridgeAvailable,
  isWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled,
  shouldUseWorkerBridge,
  terminateWorkerBridge
};
