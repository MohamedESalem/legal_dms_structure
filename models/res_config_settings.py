from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    legal_dms_storage_id = fields.Many2one(
        comodel_name="dms.storage",
        string="Legal DMS Storage",
        config_parameter="legal_dms_structure.legal_dms_storage_id",
        domain=[("save_type", "!=", "attachment")],
        help="Storage used for managed legal DMS structures.",
    )

    def set_values(self):
        result = super().set_values()
        if self.legal_dms_storage_id:
            self.env["legal.dms.service"].ensure_system_roots(self.legal_dms_storage_id)
        return result

    def action_open_legal_dms_templates(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "legal_dms_structure.action_dms_directory_template_explorer"
        )

    def action_open_legal_dms_smart_buttons(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "legal_dms_structure.action_dms_smart_button_config"
        )

    def action_open_legal_dms_backfill(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "legal_dms_structure.action_legal_dms_backfill_wizard"
        )
