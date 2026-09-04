import type { MetadataRoute } from "next";

/**
 * PWA manifest.
 *
 * `share_target` is what makes the app appear in the Android share sheet:
 * tapping Share in the YouTube app sends the link here as ?url= (or ?text=),
 * and the home page fills the field, loads the preview, and preselects Audio
 * for a YouTube Music link.
 *
 * PNG icons are required for the Android home screen and the install banner;
 * the SVG stays first for browsers that prefer it. The maskable pair lets
 * Android crop the icon into whatever shape the launcher uses.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Downloader Manager",
    short_name: "Downloader",
    description: "Paste a YouTube link, choose audio or video, and save the file.",
    lang: "en",
    dir: "ltr",
    start_url: "/",
    scope: "/",
    display: "standalone",
    display_override: ["standalone", "minimal-ui"],
    orientation: "portrait",
    background_color: "#f4f5f7",
    theme_color: "#2857c7",
    categories: ["utilities", "productivity"],
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icon-maskable-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    shortcuts: [
      {
        name: "My downloads",
        short_name: "History",
        description: "Files you have already saved",
        url: "/history",
        icons: [{ src: "/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
    ],
    share_target: {
      action: "/",
      method: "GET",
      params: { url: "url", text: "text", title: "title" },
    },
  };
}
