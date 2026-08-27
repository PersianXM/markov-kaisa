<div align="center">

<img src="docs/assets/hero.png" alt="Markov Kai'Sa block mark: a brick-built M and a seven-slot buy path" width="720">

# MARKOV KAISA

**Live Lolalytics in. A 7-slot item set out. Maximize $U$, not raw winrate.**

[![multi champion](https://img.shields.io/badge/champions-Kai'Sa%20·%20Tristana-E85A3C?style=flat-square&labelColor=1A1A1A)](RUN.bat)
[![any rank](https://img.shields.io/badge/rank-any%20tier-E85A3C?style=flat-square&labelColor=1A1A1A)](RUN.bat)
[![live patch](https://img.shields.io/badge/patch-live-1A1A1A?style=flat-square&labelColor=E85A3C)](https://lolalytics.com/lol/kaisa/build/)
[![python](https://img.shields.io/badge/runtime-python%203-2C4A4A?style=flat-square&labelColor=1A1A1A)](markov_kaisa.py)
[![one click](https://img.shields.io/badge/launch-RUN.bat-F6F1E7?style=flat-square&labelColor=1A1A1A)](RUN.bat)

[Repo](https://github.com/PersianXM/markov-kaisa)
·
[Lolalytics](https://lolalytics.com/lol/kaisa/build/)
·
[Source](markov_kaisa.py)

<p><sub>■ ■ ■  ■ ■</sub></p>

</div>

## Overview

Markov Kai'Sa is a one-key generator for League of Legends item sets. It reads live champion ADC data from Lolalytics, scores item paths as a stagewise decision chain, and writes up to **three item sets** into the client — one U-max default plus two Gem Hunter alternatives.

**Supported champions:**

| Champion | Slug | Lane |
| :--- | :--- | :--- |
| Kai'Sa | `kaisa` | Bottom |
| Tristana | `tristana` | Bottom |

The launcher lets you pick your champion and rank with arrow keys before every run.

Silver is only the **default cursor** in the rank menu. The same protocol runs on any Lolalytics bracket.

```text
YOU  ■  CHAMPION  ■  LOLALYTICS  ■  SCORE U  ■  ITEMSETS.JSON
```

<p align="center"><sub>■  ■ ■ ■ ■ ■  ■</sub></p>

## Features

<table>
<tr>
<td width="33%" valign="top">
<img src="docs/assets/icon-live.png" alt="stacked live-data bricks" width="40"><br>
<strong>LIVE PATCH</strong><br>
Reads the patch Lolalytics is serving now. No hardcoded version.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-rank.png" alt="three rank bricks" width="40"><br>
<strong>ANY RANK</strong><br>
Arrow keys in <code>RUN.bat</code>. Iron through Challenger, plus the <code>+ / all</code> filters.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-utility.png" alt="U-shaped brick" width="40"><br>
<strong>U, NOT RAW WR</strong><br>
Shrinkage, delta vs baseline, then an uncertainty penalty.
</td>
</tr>
<tr>
<td width="33%" valign="top">
<img src="docs/assets/icon-slots.png" alt="seven inventory bricks" width="40"><br>
<strong>7 SLOTS</strong><br>
Six legendaries and boots. Item 6 uses late presence when the API stops at 5.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-check.png" alt="check built from bricks" width="40"><br>
<strong>NEXT-DAY CHECK</strong><br>
Yesterday's core is rescored on today's sample: stable, faded, or improved.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-prior.png" alt="two-layer prior bricks" width="40"><br>
<strong>RANK + PRIOR</strong><br>
Your rank is the likelihood. A thicker nearby rank is the late-item prior.
</td>
</tr>
<tr>
<td width="33%" valign="top">
<img src="docs/assets/icon-utility.png" alt="U-shaped brick" width="40"><br>
<strong>GEM HUNTER</strong><br>
Relaxes floors, scores rarity, writes two extra item sets. Default Markov stays.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-rank.png" alt="champion pick bricks" width="40"><br>
<strong>MULTI CHAMPION</strong><br>
Pick Kai'Sa or Tristana in the launcher. Each champion gets its own history and item sets.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-live.png" alt="counter bricks" width="40"><br>
<strong>LIVE COUNTERS</strong><br>
Pre-built late-item branches for your hardest matchups from live counter data.
</td>
</tr>
</table>

<p align="center"><sub>■ ■    ■ ■ ■</sub></p>

## Architecture

<div align="center">
<img src="docs/assets/architecture.png" alt="Block pipeline: YOU to LOLALYTICS to SCORE U to ITEM SET" width="720">
</div>

```text
┌──────────┐     ┌──────────────┐     ┌──────────┐     ┌───────────┐
│   YOU    │ ──► │  LOLALYTICS  │ ──► │  SCORE U │ ──► │ 3 SETS    │
│  champ + │     │ Actually-    │     │ shrink,  │     │ U + 2 gem │
│  rank +  │     │ Built paths  │     │ Δ, CI, G │     │ hunters   │
│  RUN.bat │     │ + counters   │     │          │     │           │
└──────────┘     └──────────────┘     └──────────┘     └───────────┘
```

State is the items already bought. Action is the next brick. Reward is conditional $U$.

<p align="center"><sub>■ ■ ■ ■  ■</sub></p>

## Installation

Needs **Python 3**. No pip packages — stdlib only. Clone, then double-click the launcher.

```bat
git clone https://github.com/PersianXM/markov-kaisa.git
cd markov-kaisa
RUN.bat
```

League install path is in `config.json` (`league_root`). Default points at `G:\Riot Games\League of Legends`.

<p align="center"><sub>■  ■ ■  ■</sub></p>

## Quick Start

1. Run `RUN.bat`.
2. **Up / Down** to pick a champion. **Enter** confirms. **Esc** cancels.
3. **Up / Down** to pick a rank. **Enter** confirms. **Esc** cancels.
4. Wait for the fetch + score pass.
5. Fully close League, then reopen it.
6. Select your champion. Open **Item Sets**. Use **Markov \<Champion\>**.

```bat
RUN.bat
```

<p align="center"><sub>■ ■ ■  ■ ■ ■</sub></p>

## Usage

### Launcher (recommended)

```bat
RUN.bat
```

The launcher shows two interactive menus (champion → rank), runs the protocol, and installs three item sets into the League client.

### Command line

```bash
# Interactive champion + rank picker
python markov_kaisa.py --pick-champ
python markov_kaisa.py --pick-tier

# Direct run with arguments
python markov_kaisa.py --champion kaisa --tier silver
python markov_kaisa.py --champion tristana --tier gold
python markov_kaisa.py --champion kaisa --tier emerald_plus
```

| Flag | Effect |
| :--- | :--- |
| `--champion`, `--champ` | Champion to build for (`kaisa`, `tristana`) |
| `--pick-champion`, `--pick-champ` | Interactive champion picker menu |
| `--tier` | Lolalytics rank filter (`iron` … `challenger`, `platinum_plus`, `all`) |
| `--pick-tier` | Interactive rank picker menu |

### Output files

| Brick | Writes |
| :--- | :--- |
| `output/decision.json` | Scores, $U$, grid, gem data |
| `output/validation.json` | Daily validation results |
| `output/RIOT_ItemSet_Markov.json` | Main U-max item set |
| `output/RIOT_ItemSet_GemHunter_1.json` | Gem Hunter slot 1 |
| `output/RIOT_ItemSet_GemHunter_2.json` | Gem Hunter slot 2 |
| `history/daily.jsonl` | Validation snapshots |
| `Config\Champions\<Champ>\Recommended\` | Client item sets |
| `Config\ItemSets.json` | Client item set index |

<p align="center"><sub>■ ■  ■  ■ ■</sub></p>

## Configuration

Edit `config.json` for paths and floors. Champion and rank do **not** belong there for daily use — pick them in the launcher.

| Key | Role | Default |
| :--- | :--- | :--- |
| `league_root` | League install path | `G:\Riot Games\League of Legends` |
| `alpha_rank` | Empirical Bayes shrinkage strength | `800` |
| `lambda_risk` | CI penalty weight | `0.55` |
| `n_min_*` | Hard sample floors by stage (scale on fresh patches) | varies |
| `min_pick_share_*` | Drop rare paths below this share | varies |
| `core_search_k` | How many cores enter joint search | `3` |
| `fade_blacklist_streak` | Consecutive faded days before blacklisting a core | `3` |
| `fade_blacklist_days` | Duration of a core blacklist | `7` |
| `gem_alpha_scale` | Gem shrinkage relative to U path | `0.25` |
| `gem_lambda_scale` | Gem CI penalty relative to U path | `0.65` |
| `gem_n_min_core` | Absolute sample floor for a gem core | `120` |
| `gem_prior_tier` | Discovery sample for underpicked cores | `platinum_plus` |
| `gem_max_pick_share` | Prefer cores below this share | `0.12` |
| `gem_rarity_bonus` | Rarity log-bonus weight | `0.005` |
| `gem_count` | Extra item sets to write | `2` |

```json
{
  "build_title": "Markov Kai'Sa",
  "champion": "kaisa",
  "tier": "silver",
  "region": "euw",
  "alpha_rank": 800,
  "lambda_risk": 0.55
}
```

<p align="center"><sub>■    ■ ■ ■ ■</sub></p>

## The formula

<div align="center">
<img src="docs/assets/formula-u.png" alt="U equals shrunk winrate minus baseline, minus lambda times CI95" width="720">
</div>

Raw winrate is the wrong objective. It rewards rare paths and paths that only finish when you are already winning.

$$
\hat p = \frac{W}{n}
\qquad
\tilde p = \frac{W + \alpha\, p_0}{n + \alpha}
\qquad
\Delta = \tilde p - p_{\mathrm{avg}}
$$

$$
\mathrm{CI}_{95} = 1.96 \sqrt{\frac{\tilde p\,(1-\tilde p)}{n+\alpha}}
\qquad
U = \Delta - \lambda\cdot\mathrm{CI}_{95}
$$

| Symbol | Meaning |
| :---: | :--- |
| $W,\,n$ | Actually-Built wins and games |
| $p_0$ | Champion WR in that rank/region |
| $p_{\mathrm{avg}}$ | Baseline, usually $0.50$ |
| $\alpha$ | Shrinkage |
| $\lambda$ | Risk penalty |
| $U$ | What we maximize |

A path with $n < n_{\min}$ has no $U$. It is rejected.

### Gem Hunter scoring

Gem Hunter keeps the same $U$, then adds a rarity bonus and writes **two more item sets**. The default Markov set is unchanged. Discovery uses a thicker prior (Platinum+ / all) so an underpicked first item can still appear in a thin Silver sample.

$$
G = U_{\mathrm{gem}} + \nu \log(s_{\max} / s)
$$

$s$ is the core's pick share. Cores already chosen by the U path are excluded. Slot 1 prefers a different third item on the same first item. Slot 2 prefers a different first item. Both slots rank by $G$ from live data. Each surviving core gets its own League item set named by raw winrate (`Gem Hunter 53%`).

### Actually-Built aggregation

**Actually-Built**, not Exact: losers who FF never finish Exact rows, so Exact WR is biased down.

$$
n_t(i_1,\ldots,i_t)
=
\sum_{k \ge t}
n^{\mathrm{exact}}_k(i_1,\ldots,i_t,\,\cdot)
$$

### Joint finish search

Stagewise choice selects one item at a time:

$$
\pi^\star = \arg\max_{i_t} \; U(i_t \mid i_1,\ldots,i_{t-1})
$$

Joint finish combines all late slots into a single objective:

$$
U_{\mathrm{joint}} = \tfrac12 U_{45} + \tfrac14 U_{\mathrm{boots}} + \tfrac14 U_{6}
\qquad
U_{\mathrm{total}} = 0.55\,U_{\mathrm{core}} + 0.45\,U_{\mathrm{joint}}
$$

### Hierarchical prior

Late items use a thicker nearby rank (not KR for EUW):

$$
\tilde p_{\mathrm{hier}}
=
\frac{W_{\mathrm{rank}} + \alpha_{\mathrm{loc}}\, \hat p_{\mathrm{prior}}}{n_{\mathrm{rank}} + \alpha_{\mathrm{loc}}}
$$

| Your rank | Prior rank |
| :--- | :--- |
| Iron – Gold | Emerald / all |
| Platinum – Emerald | Diamond / all |
| Diamond – Diamond+ | Master / all |
| Master+ / all | All / all |

<p align="center"><sub>■ ■ ■ ■ ■</sub></p>

## Decision protocol

The 7-step pipeline runs every time you launch:

```text
Step 1  ─  Resolve live patch from Lolalytics HTML
Step 2  ─  Fetch Actually-Built item sets (rank + prior)
Step 3  ─  Compute baseline p₀, p_avg; scale sample floors if early patch
Step 4  ─  Select α, λ from hyperparameter grid + holdout validation
Step 5  ─  Stagewise U: Item1 → Pair → Core → Joint(boots, 4, 5, 6)
Step 6  ─  Gem Hunter: rank underpicked cores by G, build two extra sets
Step 7  ─  Daily validation: rescore yesterday's core on today's data
```

### Validation verdicts

| Verdict | Meaning |
| :--- | :--- |
| `stable` | $\lvert \Delta U \rvert < 0.005$ |
| `improved` | $\Delta U \ge +0.01$ |
| `faded` | $\Delta U \le -0.01$ |
| `mild` | In between |

Three consecutive `faded` verdicts trigger a **core blacklist** (default 7 days).

<p align="center"><sub>■ ■  ■ ■</sub></p>

## In-game item set guide

| Block | Use |
| :--- | :--- |
| Starting | Blade + potion |
| Buy order | Default 7-slot path |
| Late swaps | Replace items 4–6 only |
| Vs live weak matchups | Late swaps for hardest current counters |
| Vs tanks / burst / AP | Archetype late swaps if draft is mixed |
| Wards | Control + sweeper |
| **Markov \<Champion\>** | The U-max path. Default. |
| **Gem Hunter 53%** | Two separate underpicked cores, titled by that core's winrate. Same start/runes, own buy order. |

Do not swap the 3-item core for a situational brick. Pick late items from the
matchup block that fits the enemy team you see in that game. Pick a Gem Hunter
set only when you want the underpicked path, not the conservative U path.

<p align="center"><sub>■ ■  ■ ■</sub></p>

## Project structure

```text
markov-kaisa/
├── RUN.bat                 launcher: champion + rank picker
├── markov_kaisa.py         fetch, score, install (stdlib only)
├── config.json             paths, floors, hyper defaults
├── README.md
├── docs/assets/            block graphics for README
├── history/
│   ├── daily.jsonl         validation snapshots (gitignored)
│   └── blacklist.json      faded core blacklist (gitignored)
└── output/
    ├── decision.json       full decision payload (gitignored)
    ├── validation.json     daily check results (gitignored)
    ├── RIOT_ItemSet_*.json item set files (gitignored)
    ├── cache_items.json    DDragon item name cache
    ├── cache_champions.json DDragon champion cache
    ├── selected_champion.txt launcher state
    └── selected_rank.txt   launcher state
```

<p align="center"><sub>■  ■ ■ ■  ■</sub></p>

## Technology stack

```text
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│  PYTHON 3  │  │ LOLALYTICS │  │  DDRAGON   │  │ LEAGUE CFG │
│  stdlib    │  │  API + HTML │  │  items +   │  │ ItemSets   │
│  only      │  │  counters  │  │  champions │  │  .json     │
└────────────┘  └────────────┘  └────────────┘  └────────────┘
```

No extra pip packages for the generator. Stdlib only (`http.client`, `json`, `math`, `argparse`, `uuid`, `re`).

<p align="center"><sub>■ ■ ■    ■</sub></p>

## Roadmap

```text
[■] stagewise U
[■] joint late search
[■] any-rank picker
[■] daily holdout
[■] live counter late-item branches
[■] gem hunter (two extra item sets)
[■] multi-champion support (Kai'Sa + Tristana)
[■] champion picker menu
[■] early-patch sample floor scaling
[■] core blacklist on consecutive fades
[ ] support synergy branches
[ ] true 7-slot likelihood if Lolalytics adds itemSet6
[ ] more champions (Jinx, Vayne, …)
```

This remains an **under-model estimator**, not a causal proof of the best build.

<p align="center"><sub>■  ■  ■</sub></p>

## Contributing

Open an issue or a PR on [`PersianXM/markov-kaisa`](https://github.com/PersianXM/markov-kaisa). Keep changes small: one protocol brick per PR.

<p align="center"><sub>■ ■ ■ ■  ■ ■</sub></p>

## License

No license file is published in this repository yet. Treat the code as source-available until one is added.

---

<div align="center">

**$\arg\max U$** &nbsp;■&nbsp; not &nbsp;■&nbsp; **$\arg\max \hat p$**

<sub>■ Markov Kai'Sa ■ any rank ■ live data ■ multi champion ■</sub>

</div>
