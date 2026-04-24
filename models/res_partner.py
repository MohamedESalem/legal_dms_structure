from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    dms_directory_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Legal DMS Directory",
        copy=False,
        ondelete="set null",
    )
    dms_archived_directory_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Archived Legal DMS Directory",
        copy=False,
        ondelete="set null",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super(ResPartner, self.with_context(skip_track_dms_field_template=True)).create(
            vals_list
        )
        if self.env.context.get("skip_legal_dms_auto_create"):
            return records
        service = self.env["legal.dms.service"]
        for partner in records.filtered(service._is_client_partner):
            service.ensure_partner_directory(partner)
        return records

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("skip_legal_dms_sync"):
            return result
        service = self.env["legal.dms.service"]
        if "active" in vals:
            for partner in self.filtered(service._is_client_partner):
                if partner.active:
                    service.unarchive_record(partner)
                else:
                    service.archive_record(partner)
        if "parent_id" in vals:
            for partner in self.filtered(service._is_client_partner):
                if not service._record_has_any_directory(partner):
                    service.ensure_partner_directory(partner)
        return result

    def unlink(self):
        if any(self.mapped("dms_directory_id") | self.mapped("dms_archived_directory_id")):
            raise UserError(
                _(
                    "Legal records with linked DMS structures cannot be deleted. Archive the DMS tree instead."
                )
            )
        return super().unlink()

    def action_archive_legal_dms(self):
        self.ensure_one()
        self.env["legal.dms.service"].archive_record(self)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_unarchive_legal_dms(self):
        self.ensure_one()
        self.env["legal.dms.service"].unarchive_record(self)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_open_legal_dms_button(self):
        self.ensure_one()
        return self.env["legal.dms.service"].open_button_directory(
            self,
            self.env.context.get("legal_dms_button_config_id"),
        )
