from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DmsSmartButtonConfig(models.Model):
    _name = "dms.smart.button.config"
    _description = "Legal DMS Smart Button Configuration"
    _order = "target_model, sequence, id"

    name = fields.Char(required=True)
    target_model = fields.Selection(
        selection=[
            ("partner", "Client"),
            ("case", "Case"),
            ("subject", "Subject"),
        ],
        required=True,
        default="partner",
        index=True,
    )
    directory_type = fields.Selection(
        selection=[
            ("root", "Root"),
            ("cases", "Cases"),
            ("subjects", "Subjects"),
            ("custom", "Custom"),
        ],
        required=True,
        default="root",
        index=True,
    )
    template_id = fields.Many2one(
        comodel_name="dms.directory.template",
        string="Template Directory",
        ondelete="restrict",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.onchange("directory_type")
    def _onchange_directory_type(self):
        if self.directory_type != "custom":
            self.template_id = False

    @api.constrains("directory_type", "template_id", "target_model")
    def _check_template_id(self):
        level_by_model = {
            "partner": "client",
            "case": "case",
            "subject": "subject",
        }
        for config in self:
            if config.directory_type == "custom" and not config.template_id:
                raise ValidationError(
                    _("A custom smart button must point to a template directory.")
                )
            if config.directory_type != "custom" and config.template_id:
                raise ValidationError(
                    _("Only custom smart buttons can point to a template directory.")
                )
            if (
                config.directory_type == "custom"
                and config.template_id.level != level_by_model[config.target_model]
            ):
                raise ValidationError(
                    _("The selected template directory does not match the target model.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env["legal.dms.service"].sync_smart_button_views()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env["legal.dms.service"].sync_smart_button_views()
        return result

    def unlink(self):
        result = super().unlink()
        self.env["legal.dms.service"].sync_smart_button_views()
        return result
