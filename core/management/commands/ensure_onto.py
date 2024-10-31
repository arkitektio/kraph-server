from django.core.management.base import BaseCommand
from django.conf import settings
from core import models, builders, base_models
import json
import omegaconf


class Command(BaseCommand):
    help = "Creates all configured apps or overwrites them"

    def handle(self, *args, **options):
       
        default_ontology = models.Ontology.objects.update_or_create(
            name="Internal",
            description="An internal ontology for the core system",
        )

        ontology = models.Ontology.objects.update_or_create(
            name="Gene Ontology",
            public_url="https://www.ebi.ac.uk/ols4/ontologies/go",
            description="The Gene Ontology (GO) provides a framework and set of concepts for describing the functions of gene products from all organisms.",
        )

        entity_kind = models.EntityKind.objects.update_or_create(
            ontology=ontology,
            name="Axon Initial Segment",
            public_url="http://purl.obolibrary.org/obo/GO_0043194"
        )

        









        
