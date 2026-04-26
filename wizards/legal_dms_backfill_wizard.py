from odoo import _, fields, models


class LegalDmsBackfillWizard(models.TransientModel):
    _name = "legal.dms.backfill.wizard"
    _description = "Legal DMS Backfill Wizard"

    create_clients = fields.Boolean(default=True)
    create_cases = fields.Boolean(default=True)
    create_subjects = fields.Boolean(default=True)

    def action_backfill(self):
        self.ensure_one()
        counts = self.env["legal.dms.service"].backfill(
            create_clients=self.create_clients,
            create_cases=self.create_cases,
            create_subjects=self.create_subjects,
        )
        message = _(
            "Created %(clients)s client folders, %(cases)s case folders, and %(subjects)s subject folders. "
            "Synced %(clients_synced)s existing clients, %(cases_synced)s existing cases, and %(subjects_synced)s existing subjects."
        ) % {
            "clients": counts.get("clients", 0),
            "cases": counts.get("case", 0),
            "subjects": counts.get("subject", 0),
            "clients_synced": counts.get("clients_synced", 0),
            "cases_synced": counts.get("case_synced", 0),
            "subjects_synced": counts.get("subject_synced", 0),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Legal DMS Backfill Complete"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
