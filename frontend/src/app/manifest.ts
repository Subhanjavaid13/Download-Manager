import type { MetadataRoute } from "next";

/**
 * PWA manifest. `share_target` lets Android users tap Share in the YouTube app
 * and pick Downloader Manager; the link arrives as ?url= or ?text= on the home page.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Downloader Manager",
    short_name: "Downloader",
    description: "Paste a YouTube link, choose audio or video, and save the file.",
    start_url: "/",
    display: "standalone",
    background_color: "#f4f5f7",
    theme_color: "#2857c7",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
    share_target: {
      action: "/",
      method: "GET",
      params: { url: "url", text: "text", title: "title" },
    },
  } as MetadataRoute.Manifest;
}
