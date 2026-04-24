from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProjectProject(models.Model):
    _name = "project.project"
    _inherit = ["project.project", "dms.field.mixin"]

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
        records = super(
            ProjectProject,
            self.with_context(skip_track_dms_field_template=True),
        ).create(vals_list)
        if self.env.context.get("skip_legal_dms_auto_create"):
            return records
        service = self.env["legal.dms.service"]
        for project in records.filtered(service._is_legal_matter):
            service.ensure_project_directory(project)
        return records

    def write(self, vals):
        if self.env.context.get("skip_legal_dms_sync"):
            return super().write(vals)

        service = self.env["legal.dms.service"]
        watched_fields = {"partner_id", "matter_type", "is_template", "active"}
        watched_fields.update(service._get_project_assignment_field_names())
        previous_partners = self.mapped("partner_id")
        result = super().write(vals)
        if watched_fields.intersection(vals):
            if "active" in vals:
                for project in self:
                    if project.active:
                        service.unarchive_record(project)
                    else:
                        service.archive_record(project)
            for project in self:
                if not project.active and project.dms_archived_directory_id:
                    continue
                if service._is_legal_matter(project):
                    if project.dms_directory_id:
                        if {"partner_id", "matter_type"} & set(vals):
                            service.relocate_project_directory(project)
                        else:
                            service.sync_project_access(project)
                    else:
                        service.ensure_project_directory(project)
            if previous_partners:
                service.sync_partner_access(previous_partners.exists())
        return result

    def unlink(self):
        if any(self.mapped("dms_directory_id") | self.mapped("dms_archived_directory_id")):
            raise UserError(
                _(
                    "Legal matters with linked DMS structures cannot be deleted. Archive the DMS tree instead."
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
