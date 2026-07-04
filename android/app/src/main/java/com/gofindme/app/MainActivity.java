package com.gofindme.app;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebSettings;
import android.webkit.WebView;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Starts the bundled GoFindMe server (uvicorn on 127.0.0.1:8000, on a Python
 * thread) and shows it in a WebView.
 *
 * Portrait mobile edition: the activity is locked to portrait (also declared in
 * the manifest). Rather than blindly loading the URL after a fixed delay — which
 * flashes a "webpage not available" error while the server is still booting — we
 * show an in-app splash, poll the health endpoint until the server answers, and
 * only then load the app. If the server never starts, we surface the captured
 * Python traceback instead of a blank error page.
 */
public class MainActivity extends Activity {

    private static final String BASE = "http://127.0.0.1:8000";
    private static final String HEALTH = BASE + "/api/health";
    private static final long BOOT_TIMEOUT_MS = 90_000;   // slow first-boot headroom

    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean loaded = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Portrait lock (the manifest also declares it).
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        // Honor the page's responsive viewport; no pinch-zoom, no overview shrink.
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        setContentView(web);

        // Show an in-app splash immediately (no network) so the user never sees
        // the raw browser error while the server boots.
        web.loadDataWithBaseURL(BASE, SPLASH, "text/html", "utf-8", null);

        // Start the bundled Python server.
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            // Hand the app a writable data dir for its SQLite DB + uploads.
            Python.getInstance().getModule("android_main")
                    .callAttr("start", getFilesDir().getAbsolutePath());
        } catch (Throwable t) {
            showError("Couldn’t start the GoFindMe server.", String.valueOf(t));
            return;
        }

        // Wait for the server to answer, off the UI thread.
        new Thread(this::waitForServer, "gofindme-wait").start();
    }

    private void waitForServer() {
        long deadline = System.currentTimeMillis() + BOOT_TIMEOUT_MS;
        while (!loaded && System.currentTimeMillis() < deadline) {
            if (ping()) {
                loaded = true;
                ui.post(() -> web.loadUrl(BASE + "/"));
                return;
            }
            try {
                Thread.sleep(400);
            } catch (InterruptedException ignored) {
                return;
            }
        }
        if (!loaded) {
            // Surface any startup traceback the Python side captured.
            String detail = "";
            try {
                detail = String.valueOf(Python.getInstance()
                        .getModule("android_main").callAttr("last_error"));
            } catch (Throwable ignored) {
                // best effort
            }
            if (detail == null || detail.trim().isEmpty()) {
                detail = "The server did not respond on " + HEALTH + " within "
                        + (BOOT_TIMEOUT_MS / 1000) + "s.";
            }
            showError("GoFindMe didn’t finish starting.", detail);
        }
    }

    private boolean ping() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(HEALTH).openConnection();
            c.setConnectTimeout(1000);
            c.setReadTimeout(1500);
            return c.getResponseCode() == 200;
        } catch (IOException e) {
            return false;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    private void showError(String message, String detail) {
        final String html =
            "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
            + "<body style='background:#0a0c10;color:#eef1f6;font-family:sans-serif;margin:0;"
            + "padding:24px;line-height:1.5'>"
            + "<h2 style='color:#f2665e;margin:0 0 8px'>" + escape(message) + "</h2>"
            + "<p style='color:#8b93a7;margin:0 0 14px'>Try reopening the app. If it keeps "
            + "failing, this detail helps diagnose it:</p>"
            + "<pre style='white-space:pre-wrap;word-break:break-word;background:#12151d;"
            + "padding:12px;border-radius:10px;color:#c7d0dd;font-size:12px;overflow:auto'>"
            + escape(detail) + "</pre></body></html>";
        ui.post(() -> web.loadDataWithBaseURL(BASE, html, "text/html", "utf-8", null));
    }

    private static String escape(String s) {
        if (s == null) {
            return "";
        }
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private static final String SPLASH =
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        + "<body style='background:#0a0c10;color:#eef1f6;font-family:sans-serif;margin:0;"
        + "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh'>"
        + "<div style='width:52px;height:52px;border-radius:14px;"
        + "background:linear-gradient(135deg,#2dd4a7,#3aa0ff);display:flex;align-items:center;"
        + "justify-content:center;color:#04160f;font-weight:800;font-size:26px'>G</div>"
        + "<div style='margin-top:18px;font-weight:700;font-size:17px'>Starting GoFindMe…</div>"
        + "<div style='margin-top:6px;color:#8b93a7;font-size:13px'>Booting the investigations server</div>"
        + "</body></html>";

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
