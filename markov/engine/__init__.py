"""Markov decision, evolution, and evaluation engine."""

from markov.engine.aggregation import (
    actually_built,
    apply_share_floor,
    champion_sample_n,
    max_set_depth,
    scale_sample_floors,
)
from markov.engine.evolution import (
    calculate_item_stats,
    determine_damage_profile,
    get_adaptive_counter_items,
    get_early_components,
    track_evolution_progress,
)
from markov.engine.gem_hunter import (
    buy_plan,
    compact_path_decision,
    core_identity,
    fetch_gem_prior,
    gem_search_config,
    gem_set_title,
    gem_uid,
    hunt_gem_paths,
    rank_gem_cores,
    score_gem_path,
)
from markov.engine.grid import (
    HYPER_GRID,
    compute_hyper_grid,
    consensus_hyperparams,
    select_hyperparams,
)
from markov.engine.math_utils import (
    ci95,
    compact_score,
    hierarchical_tilde,
    late_utility,
    lookup,
    score,
    score_path,
    shrink,
)
from markov.engine.pipeline import build_decision
from markov.engine.stagewise import (
    CHAMP_TAGS,
    ITEMS_BY_TAG,
    champion_tags,
    choose_boots,
    choose_late_items,
    items_for_tags,
    joint_finish,
    list_boot_candidates,
    list_late_items,
    list_sixth_candidates,
    live_matchup_branches,
    most_common_extension,
    most_common_sixth,
    pick_late_item,
    pick_sixth_legendary,
    rank_paths,
    short_champ_name,
)
from markov.engine.validation import (
    active_blacklist,
    append_history,
    compare_metric,
    load_blacklist,
    load_history,
    previous_calendar_entry,
    rescore_selection,
    save_blacklist,
    update_blacklist,
    validate_against_previous,
    verdict_from_delta,
)
