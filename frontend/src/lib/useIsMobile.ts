import { useEffect, useState } from "react";

// True while the viewport is at the mobile chat breakpoint (matches the 920px
// media query in theme.css). Components branch on this so the mobile chat layout
// is a separate render path and the desktop one is left exactly as it was.
const QUERY = "(max-width: 920px)";

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.matchMedia(QUERY).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const onChange = () => setIsMobile(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return isMobile;
}
