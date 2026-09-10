"""Console summary formatter with color and evolution status."""

from __future__ import annotations

from pathlib import Path

from markov.client.installer import league_client_running


def print_summary(cfg: dict, decision: dict, dest: Path, index_path: Path) -> None:
    """Prints a comprehensive formatted summary of the build decision to stdout."""
    print()
    print("=" * 64)
    print(f"  {cfg['build_title']}")
    print(f"  {cfg['tier'].title()} / {cfg['region'].upper()} / Patch {cfg['patch']}")
    ctx = decision.get("context") or {}
    if ctx.get("alpha") is not None:
        print(f"  alpha={ctx['alpha']:g}  lambda={ctx.get('lambda')}  {ctx.get('hyper', {}).get('status', '')}")
    print("=" * 64)

    # Starting items & Early Components
    start_str = ", ".join(row["name"] for row in decision.get("start") or [])
    print(f"Start  : {start_str}")
    early_comp = decision.get("early_components_details") or []
    if early_comp:
        print("Spikes : " + ", ".join(f"{c['name']} ({c.get('gold', {}).get('total', '')}g)" for c in early_comp[:4]))

    # Core items
    print(f"Item 1 : {decision['item1']['name']}")
    print(f"Boots  : {decision['boots']['name']}")
    print(f"Core   : {decision['core']['name']}")
    print(
        f"         tilde={decision['core']['tilde']*100:.2f}%  "
        f"U={decision['core']['U']*100:+.2f}  n={decision['core']['n']:.0f}"
    )

    # Buy order with gold
    total_gold = decision.get("total_gold")
    gold_str = f"  (Total: {total_gold}g)" if total_gold else ""
    print(f"\nBuy order:{gold_str}")
    for i, row in enumerate(decision["buy_order"], 1):
        g = row.get("gold")
        g_txt = f" [{g}g]" if g else ""
        print(f"  {i}. {row['name']}{g_txt}")

    # Kai'Sa Evolution Status
    ev = decision.get("evolution") or {}
    if ev.get("supported"):
        print("\nKai'Sa Evolutions:")
        q = ev.get("q", {})
        if q.get("evolved"):
            lvl_str = f" (Level ~{q.get('level_estimate')})" if q.get("level_estimate") else ""
            print(f"  [Q] Evolved at {q.get('step')}{lvl_str}  [+{q.get('final_ad')} AD]")
        else:
            print(f"  [Q] Not reached  [+{q.get('final_ad')} / 100 AD]")

        e = ev.get("e", {})
        if e.get("evolved"):
            lvl_e = f" (Level ~{e.get('level_estimate')})" if e.get("level_estimate") else ""
            print(f"  [E] Evolved at {e.get('step')}{lvl_e}  [+{e.get('final_as_percent')}% AS]")
        else:
            print(f"  [E] Not reached  [+{e.get('final_as_percent')}% / 100% AS]")

        w = ev.get("w", {})
        if w.get("evolved"):
            print(f"  [W] Evolved at {w.get('step')}  [+{w.get('final_ap')} AP]")
        elif w.get("final_ap", 0) > 0:
            print(f"  [W] Not reached  [+{w.get('final_ap')} / 100 AP]")

    # Daily validation
    validation = decision.get("validation") or {}
    print("\nDaily validation")
    if validation.get("status") == "waiting":
        print(f"  {validation.get('message')}")
    elif validation.get("status") == "compared":
        print(f"  Previous snapshot: {validation.get('previous_date')}  patch {validation.get('previous_patch')}")
        print(f"  Yesterday's core: {validation.get('previous_core')}")
        if validation.get("policy_changed"):
            print("  Policy changed: today's selected core is different.")
        for check in validation.get("checks") or []:
            y = check.get("yesterday") or {}
            t = check.get("today") or {}
            du = check.get("delta_U")
            du_txt = "n/a" if du is None else f"{du*100:+.2f}pp"
            yn = y.get("n")
            tn = t.get("n")
            yu = y.get("U")
            tu = t.get("U")
            yu_txt = "n/a" if yu is None else f"{yu*100:+.2f}"
            tu_txt = "n/a" if tu is None else f"{tu*100:+.2f}"
            print(
                f"  {check['label']:<6} {check['verdict']:<8} "
                f"U {yu_txt} -> {tu_txt}  dU={du_txt}  "
                f"n {yn if yn is not None else '-'} -> {tn if tn is not None else '-'}"
            )
        print(f"  {validation.get('note')}")

    # Matchup branches
    policy_branches = decision.get("policy_branches") or []
    if policy_branches:
        print("\nMatchup branches (adaptive late swaps)")
        for branch in policy_branches:
            champs = branch.get("champions") or []
            suffix = f"  [{', '.join(champs)}]" if champs else ""
            print(
                f"  {branch['title']}: "
                + ", ".join(row["name"] for row in branch.get("items") or [])
                + suffix
            )

    # Gem Hunter
    gems = decision.get("gems") or []
    if gems:
        print("\nGem Hunter")
        for gem in gems:
            g = gem.get("gem") or {}
            share = g.get("share")
            share_txt = "n/a" if share is None else f"{share*100:.1f}%"
            gu = (gem.get("core") or {}).get("U")
            tu = "n/a" if gu is None else f"{gu*100:+.2f}"
            gg = g.get("G")
            gg_txt = "n/a" if gg is None else f"{gg*100:+.2f}"
            print(f"  {gem.get('set_title')}")
            print(
                f"    core {(gem.get('core') or {}).get('name')}  "
                f"U={tu}  G={gg_txt}  share={share_txt}  "
                f"n={(gem.get('core') or {}).get('n')}"
            )
            print(
                "    buy: "
                + " -> ".join(row["name"] for row in gem.get("buy_order") or [])
            )

    champ_name = cfg.get("champion_name") or cfg.get("champion", "Kai'Sa").title()
    print(f"\nChampion file:\n  {dest}")
    print(f"Client index:\n  {index_path}")
    if league_client_running():
        print("\nLeague is open. Close the client completely, then reopen it.")
        print("Otherwise the client may overwrite ItemSets.json on exit.")
    else:
        print(f"\nOpen League and select {champ_name}. The sets appear under Item Sets.")
        print(f"{cfg['build_title']} is the U path. Gem Hunter sets are named by core winrate.")
