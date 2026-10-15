import app from "./app.js";
import settings from "./settings.js";
import scan from "./scan.js";
import results from "./results.js";
export const mockApi = { ...app, ...settings, ...scan, ...results };
export default mockApi;
