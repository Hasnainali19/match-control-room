# 2-minute demo video script

**Setup:** run `uvicorn match_insights.server:app`. Open a 1440×900 browser at
`http://localhost:8000/?persona=analyst&club=HAR`. Record the screen with voice-over. Times are approximate.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:12 | Title card, then the Control Room idle | "Commentary tells you what happened. I wanted to know **when a match is turning, and why**. I'm a Lean and continuous-improvement engineer from automotive, so I brought the factory's best tool to football." |
| 0:12–0:30 | Click **★ Demo**. The pitch animates and lower thirds appear. Point at the control chart tabs | "Thirteen AI agents read a live event stream. The Control agent keeps **SPC control charts** for each team: possession, field tilt, pressing, pass completion, difficulty, tempo. It applies the same Western Electric rules used on a production line." |
| 0:30–0:50 | The **MOMENTUM SHIFT** alert drops in. The chart shows a red diamond beyond the UCL | "Here: two charts go out of control together, so it's a momentum swing. No AI guesswork, just statistics with control limits." |
| 0:50–1:10 | The **5 Whys** card fills step by step, and the pitch flank lights up pink | "The Root-Cause agent runs a live 5 Whys from the event evidence: which flank, which player, his sprint speed down nearly 30%. Fatigue. And it proposes a countermeasure, just like a shop-floor problem board." |
| 1:10–1:30 | The **Pundit panel** updates. Zoom in on the Ex-Pro's **CORRECTED** badge (56 struck through, 42 in green) | "Four pundit agents give their takes. The Ex-Pro gets carried away, so the **Referee agent** fact-checks every number against the shared state and corrects it before it goes on air. The Producer agent decides what airs and when." |
| 1:30–1:45 | Toggle **Casual**, open ⚙, pick Español, favourite club Millbrook, focus player Marlowe, Apply | "Every viewer gets their own broadcast: analyst or casual depth, their club, a focus player, their language. With Azure OpenAI connected, any language." |
| 1:45–1:55 | Flip **Chaos 30%**. Agent-ops lanes turn amber and red, while the overlays keep flowing | "And it's production-grade. I inject 30% failures. The agents retry, fall back or defer, and the score and charts stay identical to a clean run." |
| 1:55–2:00 | README validation table, then the Azure logos list | "Validated on 60 matches against hidden ground truth, and deployable on Azure Container Apps with Azure OpenAI and Application Insights. Match Control Room." |

**Tips**
- Demo mode slows to 8× around goals and swings and skips the rest.
- The default seed 11 tells the strongest fatigue story around the 63rd–69th minute. To show it, use `?autoplay=live&start=58&speed=40&player=HAR-3`.
- Record at 1440×900. Hide the browser chrome (F11).
