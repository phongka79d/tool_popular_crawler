/** Tiny observable object store. set accepts a patch or a function of current state. */
export function createStore(initial = {}) {
  let state = { ...initial };
  const listeners = new Set;
  return { get: () => state, set(patch) {
    state = { ...state, ...typeof patch === "function" ? patch(state) : patch };
    for (const fn of [...listeners])
      fn(state);
    return state;
  }, subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  } };
}
export const store = createStore();
export const get = store.get;
export const set = store.set;
export const subscribe = store.subscribe;
