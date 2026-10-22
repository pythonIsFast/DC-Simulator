package com.dcsimulator.game;

import android.app.Activity;
import android.content.pm.PackageInfo;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Hosts the local Flask server (Chaquopy) and shows the game in a WebView. */
public class MainActivity extends Activity {
    private static final String URL = "http://127.0.0.1:5000/";
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient());
        setContentView(webView);

        new Thread(() -> {
            try {
                File resDir = prepareResources();
                File dataDir = new File(getFilesDir(), "data");
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(this));
                }
                Python.getInstance().getModule("android_main")
                        .callAttr("start", resDir.getAbsolutePath(), dataDir.getAbsolutePath());
                runOnUiThread(() -> webView.loadUrl(URL));
            } catch (Exception e) {
                runOnUiThread(() -> webView.loadData(
                        "<pre>Failed to start: " + e + "</pre>", "text/html", "utf-8"));
            }
        }).start();
    }

    /** Copies frontend + schema from the APK assets once per app update. */
    private File prepareResources() throws Exception {
        File resDir = new File(getFilesDir(), "game");
        PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
        String stamp = String.valueOf(info.lastUpdateTime);
        File marker = new File(resDir, ".stamp");
        if (marker.exists() && stamp.equals(readText(marker))) {
            return resDir;
        }
        deleteRecursive(resDir);
        resDir.mkdirs();
        copyAsset("frontend", new File(resDir, "frontend"));
        copyAsset("schema.sql", new File(resDir, "schema.sql"));
        try (OutputStream out = new FileOutputStream(marker)) {
            out.write(stamp.getBytes("UTF-8"));
        }
        return resDir;
    }

    private void copyAsset(String assetPath, File target) throws IOException {
        String[] children = getAssets().list(assetPath);
        if (children != null && children.length > 0) {
            target.mkdirs();
            for (String child : children) {
                copyAsset(assetPath + "/" + child, new File(target, child));
            }
            return;
        }
        try (InputStream in = getAssets().open(assetPath);
             OutputStream out = new FileOutputStream(target)) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
        }
    }

    private static String readText(File f) throws IOException {
        try (InputStream in = new java.io.FileInputStream(f)) {
            byte[] data = new byte[(int) f.length()];
            int off = 0;
            while (off < data.length) {
                int n = in.read(data, off, data.length - off);
                if (n < 0) break;
                off += n;
            }
            return new String(data, "UTF-8");
        }
    }

    private static void deleteRecursive(File f) {
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) deleteRecursive(k);
        }
        f.delete();
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
