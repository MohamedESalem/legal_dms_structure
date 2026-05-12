from odoo import _, fields, models


class LegalDmsBackfillWizard(models.TransientModel):
    _name = "legal.dms.backfill.wizard"
    _description = "Legal DMS Backfill Wizard"

    primary_lang_id = fields.Many2one(
        comodel_name="res.lang",
        string="Primary Language for This Run",
        required=True,
        domain=[("active", "=", True)],
        default=lambda self: (
            self.env["res.lang"].search([("code", "=", self.env.user.lang)], limit=1)
            or self.env["res.lang"].search([("active", "=", True)], limit=1)
        ),
        help="Language context used while creating or syncing folders, and optional seed for missing translations.",
    )
    init_missing_translations = fields.Boolean(
        string="Fill Missing Name Translations",
        help="If enabled, copies the primary language folder and button names into other installed languages only where a translation is still empty.",
    )
    create_clients = fields.Boolean(
        string="Clients",
        default=True,
        help="Create or sync top-level client DMS folders.",
    )
    create_cases = fields.Boolean(
        string="Cases",
        default=True,
        help="Create or sync case matter folders.",
    )
    create_subjects = fields.Boolean(
        string="Subjects",
        default=True,
        help="Create or sync subject matter folders.",
    )

    def action_backfill(self):
        self.ensure_one()
        lang = self.primary_lang_id.code
        if not lang:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Legal DMS Backfill"),
                    "message": _("Please select a valid language."),
                    "type": "danger",
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        service = self.env["legal.dms.service"].with_context(
            legal_dms_force_structure_lang=lang,
        )
        counts = service.backfill(
            create_clients=self.create_clients,
            create_cases=self.create_cases,
            create_subjects=self.create_subjects,
        )
        if self.init_missing_translations:
            service.init_legal_dms_translations_from_lang(lang)
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
        if self.init_missing_translations:
            message = _("%(summary)s Empty name translations were filled from the primary language where needed.") % {
                "summary": message,
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
