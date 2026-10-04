# Color interpretation

Use this file when supplied color differs across tools, exports, displays or physical output.
`lps-system` owns CSS delivery, interpolation and token renditions; `lapis` owns role choice and
physical output conditions. This reference adds no profile lookup or conversion capability.

Keep coordinates, named encoding/space, linear-light versus encoded values, reference white,
observer, physical measurement condition, gamut, device/process profile and dynamic range distinct.
Display P3 is a gamut, not HDR. A larger gamut does not guarantee a larger luminance range or an
accurate physical match. Physical measurement metadata belongs only where physical color is the
source or acceptance target, not as ceremony for every known-sRGB token.

Known CSS sRGB has a defined interpretation; an arbitrary RGB tuple or untagged image needs the
format/application's governing rule or stays ambiguous. Assigning a profile reinterprets unchanged
numbers; conversion derives destination numbers to preserve appearance within stated limits.
Neither operation proves calibration. Preserve source coordinates and precision beside renditions.

Encoded channels are not linear light. A colorimetric/luminance operation decodes the named source
once, works in the required linear space and re-encodes only for its destination. Reference-white
adaptation, chromatic gamut mapping and HDR tone mapping solve different problems; do not silently
clamp intermediate values or call mapping lossless. OKLCH lightness is not a contrast ratio.

Trace a discrepancy through source/tag, export, optimizer/CDN, declaration/canvas, compositing and
output rather than sampling a screenshot into the authority. Record which stage strips, converts
or preserves profiles and which destination rendition was reviewed. Parsing a wide-gamut value is
not display support; a capability query is not a panel measurement. A soft proof is simulation,
not certification or a substitute for a provider-approved physical proof.
