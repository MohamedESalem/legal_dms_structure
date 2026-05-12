from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DmsDirectoryTemplate(models.Model):
    _name = "dms.directory.template"
    _description = "Legal DMS Directory Template"
    _order = "level, sequence, id"
    _parent_store = True
    _parent_name = "parent_id"
    _rec_name = "complete_name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    level = fields.Selection(
        selection=[
            ("client", _("Client")),
            ("case", _("Case")),
            ("subject", _("Subject")),
        ],
        required=True,
        default="client",
        index=True,
    )
    usage = fields.Selection(
        selection=[
            ("normal", _("Normal")),
            ("clients_root", _("Clients Root")),
            ("archive_root", _("Archive Root")),
            ("cases_container", _("Cases Container")),
            ("subjects_container", _("Subjects Container")),
        ],
        required=True,
        default="normal",
        index=True,
    )
    parent_id = fields.Many2one(
        comodel_name="dms.directory.template",
        string="Parent Template",
        index=True,
        ondelete="cascade",
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        comodel_name="dms.directory.template",
        inverse_name="parent_id",
        string="Child Templates",
    )
    complete_name = fields.Char(compute="_compute_complete_name", store=True, recursive=True)

    @api.depends_context("lang")
    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for template in self:
            if template.parent_id:
                template.complete_name = (
                    f"{template.parent_id.complete_name} / {template.name}"
                )
            else:
                template.complete_name = template.name

    @api.constrains("parent_id", "level")
    def _check_level_consistency(self):
        for template in self.filtered("parent_id"):
            if template.parent_id.level != template.level:
                raise ValidationError(
                    _("Template children must stay inside the same level.")
                )

    @api.constrains("usage", "level", "parent_id")
    def _check_usage(self):
        for template in self:
            if template.usage in {"cases_container", "subjects_container"} and template.level != "client":
                raise ValidationError(
                    _("Cases and subjects containers are only valid on client templates.")
                )
            if template.usage in {"cases_container", "subjects_container"} and template.parent_id:
                raise ValidationError(
                    _("Cases and subjects containers must be top-level client templates.")
                )
            if template.usage in {"clients_root", "archive_root"} and template.parent_id:
                raise ValidationError(
                    _("System root template nodes cannot have a parent template.")
                )
            if template.usage in {"clients_root", "archive_root"} and template.level != "client":
                raise ValidationError(
                    _("System root template nodes must use the client level.")
                )
            if template.active and template.usage != "normal":
                duplicate = self.search(
                    [
                        ("id", "!=", template.id),
                        ("active", "=", True),
                        ("usage", "=", template.usage),
                    ],
                    limit=1,
                )
                if duplicate:
                    usage_labels = dict(
                        self.fields_get(allfields=["usage"])["usage"]["selection"]
                    )
                    raise ValidationError(
                        _("Only one active template can use the '%s' system usage.")
                        % usage_labels.get(template.usage, template.usage)
                    )
