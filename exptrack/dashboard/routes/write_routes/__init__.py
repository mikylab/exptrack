"""
exptrack/dashboard/routes/write_routes/ — POST (mutation) API endpoints

Was a single 1940-line module with 79 public functions. Split by the same
groups handler.py already dispatches on; this package re-exports the whole
surface, so `write_routes.api_*` keeps working for every existing caller
and no import anywhere had to change.

Add a new endpoint to the submodule it belongs to, then to __all__ below.

The `_`-prefixed names re-exported at the bottom are internals that existing
tests import from here directly. They are not part of the endpoint surface
and are excluded from __all__, but dropping them would break those imports
for no benefit.
"""
from __future__ import annotations

from .admin import (
    api_clean_db,
    api_reset_db,
    api_storage_info,
    api_vacuum_db,
)
from .bulk import (
    api_bulk_delete,
    api_bulk_delete_permanent,
    api_bulk_delete_preview,
    api_bulk_export,
    api_bulk_restore,
    api_save_export,
)
from .compact import (  # noqa: F401
    _compact_cell_sources,
    _compact_git_diffs,
    _compact_preview,
    _compact_timeline_sources,
    api_compact,
    api_export_diff,
)
from .experiments import (
    api_add_artifact,
    api_add_note,
    api_add_tag,
    api_create_experiment,
    api_delete,
    api_delete_artifact,
    api_delete_permanent,
    api_delete_tag,
    api_edit_artifact,
    api_edit_command,
    api_edit_notes,
    api_edit_script,
    api_edit_tag,
    api_finish,
    api_image_path,
    api_log_path,
    api_rename,
    api_restore,
    api_save_confusion,
    api_set_stage,
)
from .metrics import (
    api_delete_metric,
    api_delete_result,
    api_edit_result,
    api_log_metric,
    api_log_result,
    api_rename_metric,
)
from .params import (
    _parse_param_value,  # noqa: F401
    api_add_param,
    api_delete_param,
    api_edit_param,
    api_rename_param,
)
from .sessions import (
    _validate_session_node,  # noqa: F401
    api_session_delete,
    api_session_delete_node,
    api_session_empty_trash,
    api_session_end,
    api_session_finalize,
    api_session_link_experiment,
    api_session_materialize_experiment,
    api_session_note_node,
    api_session_preview_delete_node,
    api_session_promote_to_checkpoint,
    api_session_purge,
    api_session_purge_node,
    api_session_rename_node,
    api_session_restore,
    api_session_restore_node,
)
from .settings import (
    api_manage_result_types,
    api_set_capture_settings,
    api_set_metric_settings,
    api_set_timezone,
)
from .studies import (  # noqa: F401
    _propagate_study_change_to_config,
    _propagate_tag_change_to_config,
    api_add_study,
    api_add_to_study,
    api_all_studies,
    api_bulk_add_to_study,
    api_create_study,
    api_delete_exp_study,
    api_delete_study,
    api_delete_tag_global,
    api_propagate_study_rename,
    api_propagate_tag_rename,
    api_remove_from_study,
)
from .toolbox import (  # noqa: F401
    _config_list_add,
    _config_list_delete,
    _config_list_update,
    api_add_command,
    api_add_todo,
    api_delete_command,
    api_delete_todo,
    api_reorder_commands,
    api_update_command,
    api_update_todo,
)

__all__ = [
    "api_add_artifact",
    "api_add_command",
    "api_add_note",
    "api_add_param",
    "api_add_study",
    "api_add_tag",
    "api_add_to_study",
    "api_add_todo",
    "api_all_studies",
    "api_bulk_add_to_study",
    "api_bulk_delete",
    "api_bulk_delete_permanent",
    "api_bulk_delete_preview",
    "api_bulk_export",
    "api_bulk_restore",
    "api_clean_db",
    "api_compact",
    "api_create_experiment",
    "api_create_study",
    "api_delete",
    "api_delete_artifact",
    "api_delete_command",
    "api_delete_exp_study",
    "api_delete_metric",
    "api_delete_param",
    "api_delete_permanent",
    "api_delete_result",
    "api_delete_study",
    "api_delete_tag",
    "api_delete_tag_global",
    "api_delete_todo",
    "api_edit_artifact",
    "api_edit_command",
    "api_edit_notes",
    "api_edit_param",
    "api_edit_result",
    "api_edit_script",
    "api_edit_tag",
    "api_export_diff",
    "api_finish",
    "api_image_path",
    "api_log_metric",
    "api_log_path",
    "api_log_result",
    "api_manage_result_types",
    "api_propagate_study_rename",
    "api_propagate_tag_rename",
    "api_remove_from_study",
    "api_rename",
    "api_rename_metric",
    "api_rename_param",
    "api_reorder_commands",
    "api_reset_db",
    "api_restore",
    "api_save_confusion",
    "api_save_export",
    "api_session_delete",
    "api_session_delete_node",
    "api_session_empty_trash",
    "api_session_end",
    "api_session_finalize",
    "api_session_link_experiment",
    "api_session_materialize_experiment",
    "api_session_note_node",
    "api_session_preview_delete_node",
    "api_session_promote_to_checkpoint",
    "api_session_purge",
    "api_session_purge_node",
    "api_session_rename_node",
    "api_session_restore",
    "api_session_restore_node",
    "api_set_capture_settings",
    "api_set_metric_settings",
    "api_set_stage",
    "api_set_timezone",
    "api_storage_info",
    "api_update_command",
    "api_update_todo",
    "api_vacuum_db",
]
