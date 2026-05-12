from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    legal_dms_storage_id = fields.Many2one(
        comodel_name="dms.storage",
        string="Legal DMS Storage",
        config_parameter="legal_dms_structure.legal_dms_storage_id",
        domain=[("save_type", "!=", "attachment")],
        help="Storage used for managed legal DMS structures.",
    )
    # Stored as ir.config_parameter "legal_dms_structure.structure_lang_code" (lang code string).
    # Many2one + config_parameter on settings is unreliable across Odoo builds; use default_get/set_values.
    legal_dms_structure_lang_id = fields.Many2one(
        comodel_name="res.lang",
        string="Legal DMS Structure Language",
        domain=[("active", "=", True)],
        help="Canonical language for template-based folder names. "
        "Falls back to the company partner language when empty.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "legal_dms_structure_lang_id" not in fields_list:
            return res
        icp = self.env["ir.config_parameter"].sudo()
        code = (icp.get_param("legal_dms_structure.structure_lang_code") or "").strip()
        if not code:
            legacy_id = icp.get_param("legal_dms_structure.structure_lang_id")
            if legacy_id:
                lang = self.env["res.lang"].sudo().browse(int(legacy_id)).exists()
                if lang and lang.code:
                    code = lang.code
        if not code:
            res["legal_dms_structure_lang_id"] = False
            return res
        lang = self.env["res.lang"].sudo().search(
            [("code", "=", code), ("active", "=", True)], limit=1
        )
        res["legal_dms_structure_lang_id"] = lang.id if lang else False
        return res

    def set_values(self):
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()
        for config in self:
            if config.legal_dms_structure_lang_id:
                icp.set_param(
                    "legal_dms_structure.structure_lang_code",
                    config.legal_dms_structure_lang_id.code or "",
                )
            else:
                icp.set_param("legal_dms_structure.structure_lang_code", "")
            if config.legal_dms_storage_id:
                self.env["legal.dms.service"].ensure_system_roots(config.legal_dms_storage_id)

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
