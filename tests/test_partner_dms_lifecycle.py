from odoo.addons.base.tests.common import BaseCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestPartnerDmsLifecycle(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.storage = cls.env["dms.storage"].create(
            {"name": "Legal DMS lifecycle test", "save_type": "database"}
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "legal_dms_structure.legal_dms_storage_id", cls.storage.id
        )

    def test_crm_customer_context_does_not_create_client_directory(self):
        contact = self.env["res.partner"].with_context(
            res_partner_search_mode="customer"
        ).create(
            {"name": "CRM Prospect"}
        )

        self.assertEqual(contact.customer_rank, 1)
        self.assertFalse(contact.dms_directory_id)
        self.assertFalse(
            self.env["dms.directory"].sudo().search(
                [
                    ("legal_record_model", "=", contact._name),
                    ("legal_record_id", "=", contact.id),
                ],
                limit=1,
            )
        )

    def test_won_opportunity_creates_directory_and_name_change_renames_it(self):
        contact = self.env["res.partner"].with_context(
            res_partner_search_mode="customer"
        ).create(
            {"name": "Prospect Typo"}
        )
        open_stage = self.env["crm.stage"].search(
            [("is_won", "!=", True)], order="sequence, id", limit=1
        )
        won_stage = self.env["crm.stage"].search(
            [("is_won", "=", True)], order="sequence, id", limit=1
        )
        lead = self.env["crm.lead"].create(
            {
                "name": "Prospect Opportunity",
                "type": "opportunity",
                "partner_id": contact.id,
                "stage_id": open_stage.id,
            }
        )

        self.assertFalse(contact.dms_directory_id)
        lead.stage_id = won_stage
        directory = contact.dms_directory_id
        self.assertTrue(directory)

        contact.name = "Correct Client Name"
        service = self.env["legal.dms.service"]
        expected_name = service._compose_directory_name(
            contact.partner_sequence,
            contact.display_name,
            f"CLT-{contact.id:06d}",
        )
        self.assertEqual(directory.name, expected_name)

        service._directory_write(directory, {"name": "Legacy Stale Name"})
        service.sync_partner_directory_names()
        self.assertEqual(directory.name, expected_name)

        contact.active = False
        archived_directory = contact.dms_archived_directory_id
        contact.name = "Corrected While Archived"
        self.assertIn("Corrected While Archived", archived_directory.name)

    def test_legal_matter_promotes_unranked_contact_to_client(self):
        contact = self.env["res.partner"].create(
            {"name": "Legal Matter Client", "customer_rank": 0}
        )

        project = self.env["project.project"].create(
            {
                "name": "First Legal Subject",
                "partner_id": contact.id,
                "matter_type": "subject",
                "is_template": False,
            }
        )

        self.assertTrue(project.dms_directory_id)
        self.assertTrue(contact.dms_directory_id)
