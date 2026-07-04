package com.gofindme.app;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/**
 * Starts the bundled GoFindMe server (uvicorn on 127.0.0.1:8000, on a Python
 * thread) and shows it in a WebView. The server takes a moment to boot, so the
 * WebViewClient retries the top-level load until it answers.
 *
 * This is the portrait mobile edition: the activity is locked to portrait (also
 * declared in the manifest) so the console always renders in its phone layout.
 */
public class MainActivity extends Activity {

    private static final String URL = "http://127.0.0.1:8000/";
    private WebView web;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Belt-and-suspenders portrait lock (the manifest also declares it).
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
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    // Server may still be starting up — retry shortly.
                    handler.postDelayed(() -> view.loadUrl(URL), 1000);
                }
            }
        });
        setContentView(web);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }
        // Hand the app a writable data dir for its SQLite DB + uploads.
        Python.getInstance().getModule("android_main")
                .callAttr("start", getFilesDir().getAbsolutePath());

        handler.postDelayed(() -> web.loadUrl(URL), 1200);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
