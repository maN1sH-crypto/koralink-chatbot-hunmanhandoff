/* KoraLink website chat embed. Add this file to the site and use the snippet
   documented in README.md. The existing index.html remains the chat app. */
(function () {
    "use strict";

    var script = document.currentScript;
    if (!script || document.getElementById("koralink-chat-widget")) return;

    var chatUrl;
    var apiUrl;
    try {
        chatUrl = new URL(script.getAttribute("data-chat-url") || "../", script.src);
        apiUrl = new URL(script.getAttribute("data-api-url") || chatUrl.origin);
    } catch (error) {
        console.error("KoraLink widget: invalid data-chat-url or data-api-url.", error);
        return;
    }

    if (!["http:", "https:"].includes(chatUrl.protocol) ||
        !["http:", "https:"].includes(apiUrl.protocol)) {
        console.error("KoraLink widget: chat and API URLs must use HTTP or HTTPS.");
        return;
    }

    apiUrl.pathname = apiUrl.pathname.replace(/\/+$/, "") || "/";
    apiUrl.search = "";
    apiUrl.hash = "";

    var frameUrl = new URL(chatUrl.href);
    frameUrl.searchParams.set("embed", "1");
    frameUrl.searchParams.set("api", apiUrl.href.replace(/\/+$/, ""));

    var root = document.createElement("div");
    root.id = "koralink-chat-widget";
    var shadow = root.attachShadow({ mode: "open" });

    var style = document.createElement("style");
    style.textContent = `
        :host { all: initial; }
        .widget-root {
            position: fixed;
            right: 20px;
            bottom: 20px;
            z-index: 2147483000;
            font-family: Arial, sans-serif;
        }
        .launcher {
            display: grid;
            place-items: center;
            width: 64px;
            height: 64px;
            padding: 0;
            border: 0;
            border-radius: 50%;
            background: #303fbd;
            box-shadow: 0 4px 18px rgba(20, 32, 90, .28);
            cursor: pointer;
        }
        .launcher img { width: 52px; height: 52px; border-radius: 50%; object-fit: cover; }
        .launcher:focus-visible { outline: 3px solid #91a7ff; outline-offset: 3px; }
        .panel {
            position: absolute;
            right: 0;
            bottom: 78px;
            display: none;
            width: min(400px, calc(100vw - 32px));
            height: min(650px, calc(100dvh - 112px));
            min-height: 360px;
            overflow: hidden;
            border-radius: 18px;
            background: #fff;
            box-shadow: 0 10px 40px rgba(15, 23, 42, .22);
        }
        .panel.open { display: block; }
        iframe { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
        @media (max-width: 480px) {
            .widget-root { right: 12px; bottom: 12px; }
            .panel {
                position: fixed;
                right: 12px;
                bottom: 88px;
                width: calc(100vw - 24px);
                height: min(680px, calc(100dvh - 108px));
                min-height: 300px;
            }
        }
        @media (max-height: 480px) and (max-width: 800px) {
            .panel { height: calc(100dvh - 100px); min-height: 0; }
        }
    `;

    var container = document.createElement("div");
    container.className = "widget-root";

    var panel = document.createElement("div");
    panel.className = "panel";

    var iframe = document.createElement("iframe");
    iframe.title = "KoraLink Assistant chat";
    iframe.loading = "lazy";
    iframe.referrerPolicy = "strict-origin-when-cross-origin";

    var launcher = document.createElement("button");
    launcher.className = "launcher";
    launcher.type = "button";
    launcher.setAttribute("aria-label", "Open KoraLink Assistant chat");
    launcher.setAttribute("aria-expanded", "false");

    var icon = document.createElement("img");
    icon.alt = "";
    icon.src = script.getAttribute("data-icon-url") ||
        "https://res.cloudinary.com/tdbya9oh/image/upload/v1790333977/bot.png";
    launcher.appendChild(icon);

    function setOpen(open) {
        panel.classList.toggle("open", open);
        launcher.setAttribute("aria-expanded", String(open));
        launcher.setAttribute("aria-label", open ? "Close KoraLink Assistant chat" : "Open KoraLink Assistant chat");
        if (open && !iframe.src) iframe.src = frameUrl.href;
    }

    launcher.addEventListener("click", function () {
        setOpen(!panel.classList.contains("open"));
    });

    window.addEventListener("message", function (event) {
        if (event.source !== iframe.contentWindow || event.origin !== chatUrl.origin) return;
        if (event.data && event.data.type === "koralink-widget-close") setOpen(false);
    });

    panel.appendChild(iframe);
    container.appendChild(panel);
    container.appendChild(launcher);
    shadow.appendChild(style);
    shadow.appendChild(container);
    if (document.body) {
        document.body.appendChild(root);
    } else {
        document.addEventListener("DOMContentLoaded", function () {
            document.body.appendChild(root);
        }, { once: true });
    }
})();
