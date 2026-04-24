from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DmsDirectory(models.Model):
    _inherit = "dms.directory"

    legal_managed = fields.Boolean(copy=False, index=True)
    legal_archived = fields.Boolean(copy=False, index=True)
    legal_node_type = fields.Selection(
        selection=[
            ("clients_root", "Clients Root"),
            ("archive_root", "Archive Root"),
            ("client_root", "Client Root"),
            ("client_node", "Client Directory"),
            ("cases_container", "Cases Container"),
            ("subjects_container", "Subjects Container"),
            ("case_root", "Case Root"),
            ("subject_root", "Subject Root"),
            ("case_node", "Case Directory"),
            ("subject_node", "Subject Directory"),
        ],
        copy=False,
        index=True,
    )
    legal_template_id = fields.Many2one(
        comodel_name="dms.directory.template",
        string="Legal Template",
        copy=False,
        ondelete="restrict",
    )
    legal_record_model = fields.Char(copy=False, index=True)
    legal_record_id = fields.Integer(copy=False, index=True)

    def _legal_dms_bypass_guard(self):
        return self.env.context.get("legal_dms_allow_structure_write") or self.env.user.has_group(
            "legal_dms_structure.group_legal_dms_admin"
        )

    @classmethod
    def _legal_dms_structure_fields(cls):
        return {
            "name",
            "parent_id",
            "is_root_directory",
            "storage_id",
            "group_ids",
            "inherit_group_ids",
            "res_model",
            "res_id",
            "legal_managed",
            "legal_archived",
            "legal_node_type",
            "legal_template_id",
            "legal_record_model",
            "legal_record_id",
        }

    @classmethod
    def _legal_dms_guard_fields(cls):
        return cls._legal_dms_structure_fields()

    @classmethod
    def _legal_dms_create_error(cls):
        return _(
            "Managed legal directory structures are created automatically. Manual directory creation inside them is not allowed."
        )

    @classmethod
    def _legal_dms_write_error(cls):
        return _(
            "Managed legal directory structures cannot be renamed, moved, or reconfigured manually."
        )

    @classmethod
    def _legal_dms_unlink_error(cls):
        return _(
            "Managed legal directory structures cannot be deleted manually. Use the archive flow instead."
        )

    @classmethod
    def _legal_dms_contains_structure_values(cls, vals):
        return any(field_name in vals for field_name in cls._legal_dms_guard_fields())

    @classmethod
    def _legal_dms_contains_legal_values(cls, vals):
        return any(field_name.startswith("legal_") for field_name in vals)

    @classmethod
    def _legal_dms_contains_sensitive_write(cls, vals):
        return any(field_name in vals for field_name in cls._legal_dms_structure_fields())

    @classmethod
    def _legal_dms_any_legal_values(cls, vals):
        return cls._legal_dms_contains_legal_values(vals)

    @classmethod
    def _legal_dms_has_sensitive_fields(cls, vals):
        return cls._legal_dms_contains_sensitive_write(vals)

    @classmethod
    def _legal_dms_is_manual_sensitive_write(cls, vals):
        return cls._legal_dms_has_sensitive_fields(vals)

    @classmethod
    def _legal_dms_is_manual_sensitive_create(cls, vals):
        return cls._legal_dms_contains_structure_values(vals)

    @classmethod
    def _legal_dms_check_parent(cls, parent):
        return bool(parent and parent.legal_managed)

    @classmethod
    def _legal_dms_raise_create(cls):
        raise UserError(cls._legal_dms_create_error())

    @classmethod
    def _legal_dms_raise_write(cls):
        raise UserError(cls._legal_dms_write_error())

    @classmethod
    def _legal_dms_raise_unlink(cls):
        raise UserError(cls._legal_dms_unlink_error())

    @classmethod
    def _legal_dms_has_legal_metadata(cls, vals):
        return cls._legal_dms_any_legal_values(vals)

    @classmethod
    def _legal_dms_is_manual_create_blocked(cls, vals, parent):
        return cls._legal_dms_has_legal_metadata(vals) or cls._legal_dms_check_parent(parent)

    @classmethod
    def _legal_dms_is_manual_write_blocked(cls, vals, record, parent):
        return (
            cls._legal_dms_is_manual_sensitive_write(vals)
            and (record.legal_managed or cls._legal_dms_check_parent(parent))
        )

    @classmethod
    def _legal_dms_is_manual_unlink_blocked(cls, record):
        return bool(record.legal_managed)

    @classmethod
    def _legal_dms_parent_from_vals(cls, env, vals):
        parent_id = vals.get("parent_id")
        if not parent_id:
            return env["dms.directory"]
        return env["dms.directory"].browse(parent_id)

    @classmethod
    def _legal_dms_allow_manual_operation(cls, env):
        return env.context.get("legal_dms_allow_structure_write") or env.user.has_group(
            "legal_dms_structure.group_legal_dms_admin"
        )

    @classmethod
    def _legal_dms_guard_create(cls, env, vals_list):
        if cls._legal_dms_allow_manual_operation(env):
            return
        for vals in vals_list:
            parent = cls._legal_dms_parent_from_vals(env, vals)
            if cls._legal_dms_is_manual_create_blocked(vals, parent):
                cls._legal_dms_raise_create()

    @classmethod
    def _legal_dms_guard_write(cls, records, vals):
        if cls._legal_dms_allow_manual_operation(records.env):
            return
        if not cls._legal_dms_has_sensitive_fields(vals):
            return
        parent = cls._legal_dms_parent_from_vals(records.env, vals)
        for record in records:
            if cls._legal_dms_is_manual_write_blocked(vals, record, parent):
                cls._legal_dms_raise_write()

    @classmethod
    def _legal_dms_guard_unlink(cls, records):
        if cls._legal_dms_allow_manual_operation(records.env):
            return
        for record in records:
            if cls._legal_dms_is_manual_unlink_blocked(record):
                cls._legal_dms_raise_unlink()

    @api.model_create_multi
    def create(self, vals_list):
        self._legal_dms_guard_create(self.env, vals_list)
        return super().create(vals_list)

    def write(self, vals):
        self._legal_dms_guard_write(self, vals)
        return super().write(vals)

    def unlink(self):
        self._legal_dms_guard_unlink(self)
        return super().unlink()
