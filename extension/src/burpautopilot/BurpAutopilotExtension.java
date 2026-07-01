package burpautopilot;

import burp.api.montoya.BurpExtension;
import burp.api.montoya.MontoyaApi;
import burp.api.montoya.http.HttpService;
import burp.api.montoya.http.message.HttpRequestResponse;
import burp.api.montoya.http.message.requests.HttpRequest;
import burp.api.montoya.http.message.responses.HttpResponse;
import burp.api.montoya.scanner.AuditConfiguration;
import burp.api.montoya.scanner.BuiltInAuditConfiguration;
import burp.api.montoya.scanner.Crawl;
import burp.api.montoya.scanner.CrawlConfiguration;
import burp.api.montoya.scanner.ScanTask;
import burp.api.montoya.scanner.audit.Audit;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Burp Autopilot companion extension.
 *
 * Exposes — over a loopback-only HTTP/JSON endpoint — the capabilities the "MCP Server" extension
 * does NOT provide: launching active scans/crawls, polling their status, and scripted fuzzing with
 * machine-readable result harvesting (an Intruder-equivalent built on the Montoya HTTP API, since
 * Burp's GUI Intruder attack engine is not programmable).
 *
 * Driven by the skill's burp_client.py (`scan-start`, `scan-status`, `fuzz`). Bind address is
 * always 127.0.0.1. An optional shared token (env BURP_AUTOPILOT_TOKEN) gates every request.
 */
public class BurpAutopilotExtension implements BurpExtension {

    private static final int DEFAULT_PORT = 9877;
    private static final int FUZZ_HARD_CAP = 1000;       // absolute ceiling on requests per fuzz call
    private static final int MAX_BODY = 2_000_000;       // max request body bytes (DoS guard)
    private static final int MAX_BASEREQ_LEN = 1_000_000;
    private static final int MAX_PAYLOAD_LEN = 100_000;

    /** Carries an HTTP status so handlers can reply with the right code. */
    private static final class BadRequest extends RuntimeException {
        final int code;
        BadRequest(int code, String msg) { super(msg); this.code = code; }
    }

    private MontoyaApi api;
    private HttpServer server;
    private ExecutorService pool;
    private String token; // null => no auth (loopback only)

    private final Map<String, TaskEntry> tasks = new ConcurrentHashMap<>();
    private final AtomicInteger taskSeq = new AtomicInteger(0);

    private static final class TaskEntry {
        final String type;     // "audit" or "crawl"
        final ScanTask task;
        TaskEntry(String type, ScanTask task) { this.type = type; this.task = task; }
    }

    @Override
    public void initialize(MontoyaApi api) {
        this.api = api;
        api.extension().setName("Burp Autopilot Companion");

        this.token = trimToNull(System.getenv("BURP_AUTOPILOT_TOKEN"));
        int port = DEFAULT_PORT;
        String portEnv = trimToNull(System.getenv("BURP_AUTOPILOT_PORT"));
        if (portEnv != null) {
            try { port = Integer.parseInt(portEnv); } catch (NumberFormatException ignored) { }
        }

        try {
            server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), port), 0);
        } catch (IOException e) {
            api.logging().logToError("Autopilot: failed to bind 127.0.0.1:" + port, e);
            return;
        }
        pool = Executors.newFixedThreadPool(4);
        server.setExecutor(pool);

        server.createContext("/health", this::handleHealth);
        server.createContext("/scan-start", this::handleScanStart);
        server.createContext("/scan-status", this::handleScanStatus);
        server.createContext("/fuzz", this::handleFuzz);
        server.start();

        api.extension().registerUnloadingHandler(() -> {
            if (server != null) server.stop(0);
            if (pool != null) pool.shutdownNow();
            api.logging().logToOutput("Autopilot: stopped");
        });

        api.logging().logToOutput("Autopilot: listening on http://127.0.0.1:" + port
                + (token != null ? " (token required)" : " (no token - loopback only)"));
    }

    // --- handlers -------------------------------------------------------------------------

    private void handleHealth(HttpExchange ex) throws IOException {
        if (!authorized(ex)) { sendJson(ex, 401, err("unauthorized")); return; }
        JSONObject o = new JSONObject();
        o.put("ok", true);
        o.put("extension", "burp-autopilot");
        o.put("activeTasks", tasks.size());
        sendJson(ex, 200, o);
    }

    private void handleScanStart(HttpExchange ex) throws IOException {
        if (!authorized(ex)) { sendJson(ex, 401, err("unauthorized")); return; }
        try {
            JSONObject body = readJson(ex);
            String type = body.optString("type", "audit").toLowerCase();
            JSONArray urls = body.optJSONArray("urls");
            boolean requireInScope = body.optBoolean("requireInScope", false);
            if (urls == null || urls.isEmpty()) { sendJson(ex, 400, err("urls[] required")); return; }

            JSONArray rejected = new JSONArray();
            for (int i = 0; i < urls.length(); i++) {
                String u = urls.getString(i);
                if (requireInScope && !api.scope().isInScope(u)) rejected.put(u);
            }
            if (rejected.length() > 0) {
                sendJson(ex, 400, err("out-of-scope urls rejected (requireInScope)").put("rejected", rejected));
                return;
            }

            String id = "task-" + taskSeq.incrementAndGet();
            JSONObject resp = new JSONObject().put("taskId", id).put("type", type);

            if (type.equals("crawl")) {
                String[] seeds = toStringArray(urls);
                Crawl crawl = api.scanner().startCrawl(CrawlConfiguration.crawlConfiguration(seeds));
                tasks.put(id, new TaskEntry("crawl", crawl));
                resp.put("seedCount", seeds.length);
            } else if (type.equals("audit")) {
                AuditConfiguration cfg = AuditConfiguration.auditConfiguration(
                        BuiltInAuditConfiguration.LEGACY_ACTIVE_AUDIT_CHECKS);
                Audit audit = api.scanner().startAudit(cfg);
                JSONArray added = new JSONArray();
                for (int i = 0; i < urls.length(); i++) {
                    String u = urls.getString(i);
                    try { audit.addRequest(HttpRequest.httpRequestFromUrl(u)); added.put(u); }
                    catch (Exception e) { rejected.put(u + " (" + e.getMessage() + ")"); }
                }
                tasks.put(id, new TaskEntry("audit", audit));
                resp.put("addedCount", added.length());
                if (rejected.length() > 0) resp.put("addErrors", rejected);
            } else {
                sendJson(ex, 400, err("type must be 'audit' or 'crawl'"));
                return;
            }
            sendJson(ex, 200, resp);
        } catch (BadRequest br) {
            sendJson(ex, br.code, err(br.getMessage()));
        } catch (Exception e) {
            api.logging().logToError("scan-start failed", e);
            sendJson(ex, 400, err("scan-start failed: " + e.getMessage()));
        }
    }

    private void handleScanStatus(HttpExchange ex) throws IOException {
        if (!authorized(ex)) { sendJson(ex, 401, err("unauthorized")); return; }
        try {
            Map<String, String> q = queryParams(ex);
            String id = q.get("taskId");
            if (id == null || id.equals("all")) {
                JSONArray arr = new JSONArray();
                for (Map.Entry<String, TaskEntry> e : tasks.entrySet()) {
                    arr.put(statusOf(e.getKey(), e.getValue()));
                }
                sendJson(ex, 200, new JSONObject().put("tasks", arr));
                return;
            }
            TaskEntry te = tasks.get(id);
            if (te == null) { sendJson(ex, 404, err("unknown taskId: " + id)); return; }
            sendJson(ex, 200, statusOf(id, te));
        } catch (BadRequest br) {
            sendJson(ex, br.code, err(br.getMessage()));
        } catch (Exception e) {
            api.logging().logToError("scan-status failed", e);
            sendJson(ex, 400, err("scan-status failed: " + e.getMessage()));
        }
    }

    private JSONObject statusOf(String id, TaskEntry te) {
        JSONObject o = new JSONObject();
        o.put("taskId", id);
        o.put("type", te.type);
        try {
            o.put("status", te.task.statusMessage());
            o.put("requestCount", te.task.requestCount());
            o.put("errorCount", te.task.errorCount());
            if (te.task instanceof Audit) {
                Audit a = (Audit) te.task;
                o.put("insertionPointCount", a.insertionPointCount());
                o.put("issueCount", a.issues().size());
            }
        } catch (Exception e) {
            o.put("statusError", String.valueOf(e.getMessage()));
        }
        return o;
    }

    private void handleFuzz(HttpExchange ex) throws IOException {
        if (!authorized(ex)) { sendJson(ex, 401, err("unauthorized")); return; }
        try {
            JSONObject body = readJson(ex);
            String host = body.optString("host", null);
            int port = body.optInt("port", 0);
            boolean https = body.optBoolean("https", true);
            String baseRequest = body.optString("baseRequest", null);
            String placeholder = body.optString("placeholder", "§FUZZ§");
            JSONArray payloads = body.optJSONArray("payloads");
            int maxRequests = body.optInt("maxRequests", 50);
            long delayMs = body.optLong("delayMs", 0L);
            boolean requireInScope = body.optBoolean("requireInScope", false);

            if (host == null || port <= 0 || baseRequest == null || payloads == null) {
                sendJson(ex, 400, err("host, port, baseRequest, payloads[] are required"));
                return;
            }
            if (placeholder == null || placeholder.isEmpty()) {
                sendJson(ex, 400, err("placeholder must be a non-empty string"));
                return;
            }
            if (maxRequests <= 0) {
                sendJson(ex, 400, err("maxRequests must be >= 1"));
                return;
            }
            if (delayMs < 0) {
                sendJson(ex, 400, err("delayMs must be >= 0"));
                return;
            }
            if (baseRequest.length() > MAX_BASEREQ_LEN) {
                sendJson(ex, 413, err("baseRequest exceeds " + MAX_BASEREQ_LEN + " chars"));
                return;
            }
            if (!baseRequest.contains(placeholder)) {
                sendJson(ex, 400, err("baseRequest does not contain placeholder '" + placeholder + "'"));
                return;
            }
            int target = Math.min(maxRequests, FUZZ_HARD_CAP); // cap on actually-sent requests

            HttpService service = HttpService.httpService(host, port, https);
            JSONArray results = new JSONArray();
            JSONArray skipped = new JSONArray();
            int sentCount = 0;
            int i = 0;
            for (; i < payloads.length() && sentCount < target; i++) {
                String payload = payloads.getString(i);
                // skips do NOT consume a sent slot - keep scanning later payloads
                if (payload.length() > MAX_PAYLOAD_LEN) {
                    skipped.put(new JSONObject().put("index", i)
                            .put("reason", "payload too long (> " + MAX_PAYLOAD_LEN + " chars)"));
                    continue;
                }
                String raw = baseRequest.replace(placeholder, payload);
                HttpRequest req = HttpRequest.httpRequest(service, raw);
                if (requireInScope && !api.scope().isInScope(req.url())) {
                    skipped.put(new JSONObject().put("index", i).put("reason", "out-of-scope"));
                    continue;
                }
                long t0 = System.nanoTime();
                HttpRequestResponse rr = api.http().sendRequest(req);
                long ms = (System.nanoTime() - t0) / 1_000_000L;
                JSONObject r = new JSONObject().put("index", i).put("payload", payload).put("timeMs", ms);
                HttpResponse resp = rr.response();
                if (resp != null) {
                    r.put("status", (int) resp.statusCode());
                    r.put("length", resp.body().length());
                } else {
                    r.put("status", JSONObject.NULL);
                    r.put("error", "no response");
                }
                results.put(r);
                sentCount++;
                if (delayMs > 0 && sentCount < target) {
                    try { Thread.sleep(delayMs); } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        i++; // the payload at i was already sent - count it as processed
                        break;
                    }
                }
            }
            JSONObject out = new JSONObject().put("sent", sentCount).put("results", results);
            if (skipped.length() > 0) out.put("skipped", skipped);
            int unprocessed = payloads.length() - i;
            if (unprocessed > 0) {
                out.put("truncated", unprocessed + " payload(s) not processed (hit maxRequests/cap "
                        + target + ")");
            }
            sendJson(ex, 200, out);
        } catch (BadRequest br) {
            sendJson(ex, br.code, err(br.getMessage()));
        } catch (Exception e) {
            api.logging().logToError("fuzz failed", e);
            sendJson(ex, 400, err("fuzz failed: " + e.getMessage()));
        }
    }

    // --- helpers --------------------------------------------------------------------------

    private boolean authorized(HttpExchange ex) {
        if (token == null) return true;
        String got = ex.getRequestHeaders().getFirst("X-Autopilot-Token");
        return token.equals(got);
    }

    private JSONObject readJson(HttpExchange ex) throws IOException {
        try (InputStream in = ex.getRequestBody()) {
            byte[] bytes = in.readNBytes(MAX_BODY + 1);
            if (bytes.length > MAX_BODY) {
                throw new BadRequest(413, "request body exceeds " + MAX_BODY + " bytes");
            }
            String s = new String(bytes, StandardCharsets.UTF_8).trim();
            if (s.isEmpty()) return new JSONObject();
            return new JSONObject(new JSONTokener(s));
        }
    }

    private void sendJson(HttpExchange ex, int code, JSONObject body) throws IOException {
        byte[] out = body.toString().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(code, out.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(out); }
    }

    private static JSONObject err(String msg) { return new JSONObject().put("error", msg); }

    private static String[] toStringArray(JSONArray a) {
        String[] out = new String[a.length()];
        for (int i = 0; i < a.length(); i++) out[i] = a.getString(i);
        return out;
    }

    private static Map<String, String> queryParams(HttpExchange ex) {
        Map<String, String> map = new HashMap<>();
        String raw = ex.getRequestURI().getRawQuery();
        if (raw == null) return map;
        for (String pair : raw.split("&")) {
            int eq = pair.indexOf('=');
            if (eq < 0) continue;
            try {
                String k = URLDecoder.decode(pair.substring(0, eq), StandardCharsets.UTF_8);
                String v = URLDecoder.decode(pair.substring(eq + 1), StandardCharsets.UTF_8);
                map.put(k, v);
            } catch (IllegalArgumentException e) {
                throw new BadRequest(400, "malformed query encoding: " + e.getMessage());
            }
        }
        return map;
    }

    private static String trimToNull(String s) {
        if (s == null) return null;
        s = s.trim();
        return s.isEmpty() ? null : s;
    }
}
