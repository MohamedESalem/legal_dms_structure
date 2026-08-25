from odoo import api, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def _ensure_won_partner_dms_directories(self):
        if self.env.context.get("skip_legal_dms_sync"):
            return
        won_leads = self.filtered(
            lambda lead: lead.active and lead.stage_id.is_won and lead.partner_id
        )
        partners = won_leads.mapped("partner_id.commercial_partner_id")
        service = self.env["legal.dms.service"]
        for partner in partners.filtered(service._is_client_partner):
            if not service._record_has_any_directory(partner):
                service.ensure_partner_directory(partner)

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        leads._ensure_won_partner_dms_directories()
        return leads

    def write(self, vals):
        result = super().write(vals)
        if {"active", "partner_id", "stage_id"}.intersection(vals):
            self._ensure_won_partner_dms_directories()
        return result
