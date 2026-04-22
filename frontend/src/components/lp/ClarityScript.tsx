'use client'

import Script from 'next/script'

/**
 * Microsoft Clarity tracking snippet. Loads after the page is interactive
 * (strategy="afterInteractive") so it never blocks LCP.
 *
 * The snippet format comes from Clarity project settings → "Install manually".
 */
export default function ClarityScript({ projectId }: { projectId: string }) {
  if (!projectId) return null
  return (
    <Script id="clarity-init" strategy="afterInteractive">
      {`
      (function(c,l,a,r,i,t,y){
        c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
        t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
        y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
      })(window, document, "clarity", "script", "${projectId}");
      `}
    </Script>
  )
}
