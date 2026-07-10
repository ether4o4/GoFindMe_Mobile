package com.gofindme.app;

import android.app.Activity;
import android.content.SharedPreferences;
import android.content.pm.ActivityInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.net.HttpURLConnection;
import java.net.URL;

/**
 * GoFindMe mobile client. Two modes, chosen on a connection screen:
 *
 *  - Remote: point the app at a GoFindMe server running on a PC or VPS and use
 *    the phone as a pure dashboard. To reach that server when the phone is NOT on
 *    the same Wi-Fi, the server should be on a private tunnel (Tailscale) or a
 *    public HTTPS host (VPS) — the app just loads whatever URL you give it.
 *  - Local: run the bundled Python server on the phone (providers + vault + data;
 *    no CLI tools). This is the fallback for when you don't have a PC server.
 *
 * The chosen server is remembered. Long-press Back to return to the connection
 * screen and change it. Portrait-locked (also declared in the manifest).
 */
public class MainActivity extends Activity {

    private static final String LOCAL = "http://127.0.0.1:8000";
    private static final String PREFS = "gofindme";
    private static final String KEY_SERVER = "server_url";   // "" | "local" | a URL
    private static final long BOOT_TIMEOUT_MS = 90_000;      // slow first-boot headroom

    private WebView web;
    private SharedPreferences prefs;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean serverStarted = false;
    private volatile boolean localLoaded = false;
    private boolean showingConfig = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        web.addJavascriptInterface(new Bridge(), "GoFindMeApp");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (!req.isForMainFrame() || showingConfig) {
                    return;
                }
                String saved = prefs.getString(KEY_SERVER, "");
                if ("local".equals(saved)) {
                    // Local server may still be booting — retry shortly.
                    ui.postDelayed(() -> view.loadUrl(LOCAL + "/"), 1000);
                } else if (!TextUtils.isEmpty(saved)) {
                    showConfig("Couldn’t reach " + saved + ".\n\nCheck the address, that the "
                            + "GoFindMe server is running, and that it’s reachable from the phone "
                            + "(on Tailscale/VPS if you’re not on the same Wi-Fi).");
                }
            }
        });
        setContentView(web);

        route();
    }

    /** Decide what to show based on the saved server choice. */
    private void route() {
        String saved = prefs.getString(KEY_SERVER, "");
        if (TextUtils.isEmpty(saved)) {
            showConfig(null);
        } else if ("local".equals(saved)) {
            startLocalAndLoad();
        } else {
            connectRemote(saved);
        }
    }

    // ----------------------------- remote mode -----------------------------
    private void connectRemote(String url) {
        showingConfig = false;
        web.loadDataWithBaseURL(url, splash("Connecting…", url), "text/html", "utf-8", null);
        ui.postDelayed(() -> web.loadUrl(url), 350);
    }

    // ------------------------------ local mode -----------------------------
    private void startLocalAndLoad() {
        showingConfig = false;
        web.loadDataWithBaseURL(LOCAL, splash("Starting GoFindMe…", "Booting the local server"),
                "text/html", "utf-8", null);
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            if (!serverStarted) {
                Python.getInstance().getModule("android_main")
                        .callAttr("start", getFilesDir().getAbsolutePath());
                serverStarted = true;
            }
        } catch (Throwable t) {
            showError("Couldn’t start the local server.", String.valueOf(t));
            return;
        }
        new Thread(this::waitForLocal, "gofindme-wait").start();
    }

    private void waitForLocal() {
        long deadline = System.currentTimeMillis() + BOOT_TIMEOUT_MS;
        while (!localLoaded && System.currentTimeMillis() < deadline) {
            if (ping(LOCAL + "/api/health")) {
                localLoaded = true;
                ui.post(() -> web.loadUrl(LOCAL + "/"));
                return;
            }
            try {
                Thread.sleep(400);
            } catch (InterruptedException ignored) {
                return;
            }
        }
        if (!localLoaded) {
            String detail = "";
            try {
                detail = String.valueOf(Python.getInstance()
                        .getModule("android_main").callAttr("last_error"));
            } catch (Throwable ignored) {
                // best effort
            }
            if (detail == null || detail.trim().isEmpty()) {
                detail = "The local server did not respond within "
                        + (BOOT_TIMEOUT_MS / 1000) + "s.";
            }
            showError("GoFindMe didn’t finish starting.", detail);
        }
    }

    private boolean ping(String url) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(1000);
            c.setReadTimeout(1500);
            return c.getResponseCode() == 200;
        } catch (Throwable e) {
            return false;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    // -------------------------- connection screen --------------------------
    private void showConfig(String errorMsg) {
        showingConfig = true;
        localLoaded = false;
        ui.post(() -> web.loadDataWithBaseURL("about:blank", configHtml(errorMsg),
                "text/html", "utf-8", null));
    }

    /** Bridge exposed to the connection page only (guarded by showingConfig). */
    class Bridge {
        @JavascriptInterface
        public void connect(String url) {
            if (!showingConfig) {
                return;
            }
            final String norm = normalize(url);
            if (norm == null) {
                return;
            }
            prefs.edit().putString(KEY_SERVER, norm).apply();
            ui.post(() -> connectRemote(norm));
        }

        @JavascriptInterface
        public void useLocal() {
            if (!showingConfig) {
                return;
            }
            prefs.edit().putString(KEY_SERVER, "local").apply();
            ui.post(() -> startLocalAndLoad());
        }
    }

    private static String normalize(String url) {
        if (url == null) {
            return null;
        }
        String u = url.trim();
        if (u.isEmpty()) {
            return null;
        }
        if (!u.matches("(?i)^https?://.*")) {
            u = "https://" + u;   // default to HTTPS when no scheme given
        }
        while (u.endsWith("/")) {
            u = u.substring(0, u.length() - 1);
        }
        return u;
    }

    // Long-press Back opens the connection screen to change servers.
    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            event.startTracking();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyLongPress(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            showConfig(null);
            return true;
        }
        return super.onKeyLongPress(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && event.isTracking() && !event.isCanceled()) {
            if (!showingConfig && web.canGoBack()) {
                web.goBack();
            } else {
                finish();
            }
            return true;
        }
        return super.onKeyUp(keyCode, event);
    }

    // ------------------------------ HTML views -----------------------------
    private String configHtml(String errorMsg) {
        String saved = prefs.getString(KEY_SERVER, "");
        String prefill = (TextUtils.isEmpty(saved) || "local".equals(saved)) ? "" : escape(saved);
        String errBlock = (errorMsg == null || errorMsg.isEmpty()) ? "" :
            "<div style='background:rgba(242,102,94,.12);border:1px solid rgba(242,102,94,.4);"
            + "color:#f2665e;padding:10px 12px;border-radius:10px;font-size:13px;white-space:pre-wrap;"
            + "margin-bottom:14px'>" + escape(errorMsg) + "</div>";
        return "<!doctype html><html><head><meta name='viewport' "
            + "content='width=device-width,initial-scale=1'></head>"
            + "<body style='background:#0a0c10;color:#eef1f6;font-family:sans-serif;margin:0;"
            + "padding:calc(26px + env(safe-area-inset-top)) 22px 26px'>"
            + "<div style='max-width:460px;margin:0 auto'>"
            + "<div style='display:flex;align-items:center;gap:11px;margin-bottom:10px'>"
            + "<div style='width:38px;height:38px;border-radius:11px;"
            + "background:linear-gradient(135deg,#2dd4a7,#3aa0ff);display:flex;align-items:center;"
            + "justify-content:center;color:#04160f;font-weight:800'>G</div>"
            + "<div style='font-weight:800;font-size:18px'>Connect GoFindMe</div></div>"
            + "<p style='color:#8b93a7;font-size:13.5px;line-height:1.55;margin:0 0 18px'>"
            + "Point this app at a GoFindMe server on your PC or VPS. To reach it when you’re "
            + "<b style='color:#eef1f6'>not on the same Wi-Fi</b>, put that machine on "
            + "<b style='color:#eef1f6'>Tailscale</b> and paste its URL, or use a VPS’s HTTPS address."
            + "</p>"
            + errBlock
            + "<input id='u' value='" + prefill + "' placeholder='mybox.tailXXXX.ts.net' "
            + "autocapitalize='none' autocorrect='off' spellcheck='false' inputmode='url' "
            + "style='width:100%;box-sizing:border-box;background:#0d1017;border:1px solid #242a38;"
            + "color:#eef1f6;font-size:16px;padding:13px;border-radius:10px'/>"
            + "<button onclick=\"var v=document.getElementById('u').value;"
            + "if(v&&v.trim())GoFindMeApp.connect(v);\" "
            + "style='width:100%;margin-top:12px;background:linear-gradient(135deg,#2dd4a7,#3aa0ff);"
            + "color:#04160f;font-weight:800;font-size:15px;border:none;padding:14px;border-radius:10px'>"
            + "Connect</button>"
            + "<div style='text-align:center;color:#5b6377;font-size:12px;margin:16px 0'>or</div>"
            + "<button onclick='GoFindMeApp.useLocal()' style='width:100%;background:#171b25;"
            + "color:#eef1f6;border:1px solid #2f3648;font-weight:600;font-size:14px;padding:13px;"
            + "border-radius:10px'>Run on this phone instead</button>"
            + "<p style='color:#5b6377;font-size:11.5px;line-height:1.5;margin-top:18px'>"
            + "Tip: long-press the Back button anytime to return here and change the server.</p>"
            + "</div></body></html>";
    }

    private void showError(String message, String detail) {
        final String html =
            "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
            + "<body style='background:#0a0c10;color:#eef1f6;font-family:sans-serif;margin:0;"
            + "padding:24px;line-height:1.5'>"
            + "<h2 style='color:#f2665e;margin:0 0 8px'>" + escape(message) + "</h2>"
            + "<p style='color:#8b93a7;margin:0 0 14px'>Long-press Back to change the server, or "
            + "reopen the app. If it keeps failing, this detail helps diagnose it:</p>"
            + "<pre style='white-space:pre-wrap;word-break:break-word;background:#12151d;"
            + "padding:12px;border-radius:10px;color:#c7d0dd;font-size:12px;overflow:auto'>"
            + escape(detail) + "</pre></body></html>";
        ui.post(() -> web.loadDataWithBaseURL("about:blank", html, "text/html", "utf-8", null));
    }

    private static String splash(String title, String subtitle) {
        return "<!doctype html><html><head><meta name='viewport' "
            + "content='width=device-width,initial-scale=1'></head>"
            + "<body style='background:#0a0c10;color:#eef1f6;font-family:sans-serif;margin:0;"
            + "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh'>"
            + "<div style='width:52px;height:52px;border-radius:14px;"
            + "background:linear-gradient(135deg,#2dd4a7,#3aa0ff);display:flex;align-items:center;"
            + "justify-content:center;color:#04160f;font-weight:800;font-size:26px'>G</div>"
            + "<div style='margin-top:18px;font-weight:700;font-size:17px'>" + escape(title) + "</div>"
            + "<div style='margin-top:6px;color:#8b93a7;font-size:13px;word-break:break-all;"
            + "padding:0 24px;text-align:center'>" + escape(subtitle) + "</div>"
            + "</body></html>";
    }

    private static String escape(String s) {
        if (s == null) {
            return "";
        }
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }
}
