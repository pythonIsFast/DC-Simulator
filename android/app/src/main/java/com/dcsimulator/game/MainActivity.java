package com.dcsimulator.game;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

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
    private static final int REQ_PICK_FILE = 1;
    private static final int REQ_SAVE_FILE = 2;
    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;
    private byte[] pendingExport;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.setWebViewClient(new WebViewClient());
        // File picker for <input type="file"> (importing a save file).
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = callback;
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                try {
                    startActivityForResult(Intent.createChooser(intent, "Select save file"), REQ_PICK_FILE);
                } catch (Exception e) {
                    filePathCallback = null;
                    callback.onReceiveValue(null);
                    return false;
                }
                return true;
            }
        });
        // Saving a file (exporting a save): the page hands over the bytes, Android shows its "save as" dialog.
        webView.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void saveFile(String filename, String base64) {
                pendingExport = Base64.decode(base64, Base64.DEFAULT);
                runOnUiThread(() -> {
                    Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("application/octet-stream");
                    intent.putExtra(Intent.EXTRA_TITLE, filename);
                    startActivityForResult(intent, REQ_SAVE_FILE);
                });
            }
        }, "AndroidBridge");
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
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_PICK_FILE && filePathCallback != null) {
            filePathCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            filePathCallback = null;
        } else if (requestCode == REQ_SAVE_FILE) {
            byte[] bytes = pendingExport;
            pendingExport = null;
            if (resultCode != RESULT_OK || data == null || data.getData() == null || bytes == null) return;
            try (OutputStream out = getContentResolver().openOutputStream(data.getData())) {
                out.write(bytes);
                Toast.makeText(this, "Save file written", Toast.LENGTH_SHORT).show();
            } catch (Exception e) {
                Toast.makeText(this, "Could not write the file: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        }
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
