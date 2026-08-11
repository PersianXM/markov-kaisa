# Markov Kai'Sa

One-key generator for a Kai'Sa item set. It reads Lolalytics, applies the
Silver-EUW decision protocol, and installs the result into the League client.

## Run

Project folder: `G:\Riot\markov-kaisa`

Double-click `RUN.bat`, or press Enter after selecting it.

Rank defaults to **silver**. To use Gold data after you promote, open
`RUN.bat` and change `set RANK=silver` to `set RANK=gold`.

The item set is written to the League client index:

`G:\Riot Games\League of Legends\Config\ItemSets.json`

Then open League and select Kai'Sa. The set title is **Markov Kai'Sa**.

## Daily validation

Each run stores today's chosen core in `history/daily.jsonl`. The next calendar
day, the same paths are rescored on fresh Lolalytics data (without choosing
again). The console prints `stable`, `faded`, or `improved` for Item 1, the
2-item pair, and the 3-item core.

Late items only win if Silver sample size clears a hard floor
(`n_min_item4=800`, `n_min_item5=400`, `n_min_item6=250`) and then the
highest `U`. The inventory is **6 legendaries + boots** (7 slots). If
Lolalytics has no `itemSet6` yet, item 6 is chosen from late-game
presence on 5-item completions.

Starting items and situational items come from live data (`n_min_start`
and leftover late candidates). Rare paths below a pick-share floor are
dropped. The top cores are scored together with boots and items 4–6.
If a late slot has no path above the `n` floor, the program uses the
Most Common extension instead of a hardcoded item.

`alpha` and `lambda` use the same-day modal core across the grid, then
switch to holdout once a previous calendar day exists. A core that
fades three days in a row is blacklisted for seven days.

Skill order, rune page, hard matchups, and Vs Tanks / Burst / AP
branches are written into the item set and `output/decision.json`.
