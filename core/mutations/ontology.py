from kante.types import Info
import strawberry
from core import types, models, age, enums, scalars
from django.db import connections
from contextlib import contextmanager


@strawberry.input(description="Input type for creating a new ontology")
class OntologyInput:
    name: str = strawberry.field(
        description="The name of the ontology (will be converted to snake_case)"
    )
    description: str | None = strawberry.field(
        default=None, description="An optional description of the ontology"
    )
    purl: str | None = strawberry.field(
        default=None, description="An optional PURL (Persistent URL) for the ontology"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="An optional ID reference to an associated image"
    )
    
@strawberry.input(description="Input type for creating a new ontology node")
class OntologyNodeInput:
    age_name: str = strawberry.field(
        description="The AGE_NAME of the ontology"
    )
    kind: enums.OntologyNodeKind = strawberry.field(
        description="The kind of the ontology node"
    )
    label: str  = strawberry.field(
        description="The label of the ontdology node"
    )
    name: str | None = strawberry.field(
        description="The name of the ontology node (will be converted to snake_case)",
        default=None
    )
    description: str | None = strawberry.field(
        default=None, description="An optional description of the ontology node"
    )
    purl: str | None = strawberry.field(
        default=None, description="An optional PURL (Persistent URL) for the ontology node"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="An optional ID reference to an associated image"
    )
    identifier: scalars.StructureIdentifier | None = strawberry.field(
        default=None, description="An optional identifier for the ontology node"
    )
    position_x: float | None = strawberry.field(
        default=None, description="An optional x position for the ontology node"
    )
    position_y: float | None = strawberry.field(
        default=None, description="An optional y position for the ontology node"
    )
    height: float | None = strawberry.field(
        default=None, description="An optional height for the ontology node"
    )
    width: float | None = strawberry.field(
        default=None, description="An optional width for the ontology node"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="An optional RGBA color for the ontology node"
    )

@strawberry.input(description="Input type for creating a new ontology node")
class OntologyEdgeInput:
    age_name: str = strawberry.field(
        description="The AGE_NAME of the ontology"
    )
    kind: enums.OntologyEdgeKind = strawberry.field(
        description="The kind of the ontology node"
    )
    name: str = strawberry.field(
        description="The name of the ontology node (will be converted to snake_case)"
    )
    source: strawberry.ID = strawberry.field(
        description="The ID of the source ontology node"
    )
    target: strawberry.ID = strawberry.field(
        description="The ID of the target ontology node"
    )
    description: str | None = strawberry.field(
        default=None, description="An optional description of the ontology node"
    )
    purl: str | None = strawberry.field(
        default=None, description="An optional PURL (Persistent URL) for the ontology node"
    )
    measurement_kind: enums.MeasurementKind | None  = strawberry.field(
        description="The kind of the value for the ontology edge",
        default=None
    )
    template: strawberry.ID | None = strawberry.field(
        default=None, description="The ID of the protocol template if its a step edge"
    )
    allowed_structures: list[scalars.StructureIdentifier] | None = strawberry.field(
        default=None, description="The allowed structures for the measurement edge"
    )
    is_self_referential: bool | None = strawberry.field(
        default=None, description="Whether the edge is self-referential or needs a different source than target"
    )


@strawberry.input(description="Input type for updating an existing ontology")
class UpdateOntologyInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to update")
    name: str | None = strawberry.field(
        default=None,
        description="New name for the ontology (will be converted to snake_case)",
    )
    description: str | None = strawberry.field(
        default=None, description="New description for the ontology"
    )
    purl: str | None = strawberry.field(
        default=None, description="New PURL (Persistent URL) for the ontology"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="New ID reference to an associated image"
    )
    nodes: list[OntologyNodeInput] | None = strawberry.field(
        default=None, description="New nodes for the ontology"
    )
    edges: list[OntologyEdgeInput] | None = strawberry.field(
        default=None, description="New edges for the ontology"
    )


@strawberry.input(description="Input type for deleting an ontology")
class DeleteOntologyInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to delete")


def to_snake_case(string):
    return string.replace(" ", "_").lower()


def create_ontology(
    info: Info,
    input: OntologyInput,
) -> types.Ontology:

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item, _ = models.Ontology.objects.update_or_create(
        name=to_snake_case(input.name),
        defaults=dict(
            description=input.description or "", store=media_store, purl=input.purl
        ),
    )

    return item


def update_ontology(info: Info, input: UpdateOntologyInput) -> types.Ontology:
    item = models.Ontology.objects.get(id=input.id)

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item.name = input.name or item.name
    item.description = input.description or item.description
    item.purl = input.purl or item.purl
    item.store = media_store or item.store
    item.save()
    
    if input.nodes is not None and input.edges is not None:
        
        node_age_names = [node.age_name for node in input.nodes]
        edge_age_names = [edge.age_name for edge in input.edges]
        
        # all values in nodes and edges must be unique
        assert len(node_age_names + edge_age_names) == len(set(node_age_names + edge_age_names)), "All AGE_NAME values of nodes and edges must be unique"
        
        
        strucure_nodes = [node for node in input.nodes if node.kind == enums.OntologyNodeKind.STRUCTURE]
        entity_nodes = [node for node in input.nodes if node.kind == enums.OntologyNodeKind.ENTITY]
        
        measurement_edges = [edge for edge in input.edges if edge.kind == enums.OntologyEdgeKind.MEASUREMENT]
        step_edges = [edge for edge in input.edges if edge.kind == enums.OntologyEdgeKind.STEP]
        
            
        relation_edges = [edge for edge in input.edges if edge.kind == enums.OntologyEdgeKind.RELATION]
        
        ### Prevalidation
        
        for measurement_edge in measurement_edges:
            assert measurement_edge.measurement_kind is not None, "Measurement edges must have a measurement kind"
        for relation_edge in relation_edges:
            assert relation_edge.name is not None, "Relation edges must have a name"
        for step_edge in step_edges:   
            assert step_edge.template is not None, "Step edges must have a template"
        for node in strucure_nodes:
            assert node.identifier is not None, "Structure nodes must have an identifier"
        for node in entity_nodes:
            assert node.label is not None, "Entity nodes must have a label"
        
            
            
        
        
        for node in strucure_nodes:
            
            
            scategory, created = models.StructureCategory.objects.update_or_create(
                age_name=node.age_name,
                ontology=item,
                defaults=dict(
                    identifier=node.identifier,
                    position_x=node.position_x,
                    position_y=node.position_y,
                    description=node.description or "",
                    purl=node.purl or "",
                    height=node.height,
                    width=node.width,
                    color = node.color,
                ),
            )
            
            if created:
                print("Created new structure category")
            
        for node in entity_nodes:
            
            assert node.label is not None, "Entity nodes must have a label"
            
            ecategory, created = models.GenericCategory.objects.update_or_create(
                age_name=node.age_name,
                ontology=item,
                defaults=dict(
                    label=node.label,
                    position_x=node.position_x,
                    position_y=node.position_y,
                    description=node.description or "",
                    purl=node.purl or "",
                    height=node.height,
                    width=node.width,
                    color = node.color,
                ),
            )
            
            if created:
                print("Created new entity category")
                
        for edge in measurement_edges:
            
            
            medge, created = models.MeasurementCategory.objects.update_or_create(
                age_name=edge.age_name,
                ontology=item,
                defaults=dict(
                    metric_kind=edge.measurement_kind,
                    description=edge.description or "",
                    purl=edge.purl or "",
                    left=models.Expression.objects.get(age_name=edge.source, ontology=item),
                    right=models.Expression.objects.get(age_name=edge.target, ontology=item),
                ),
            )
            
            if created:
                print("Created new measurement edge")
                
        for edge in relation_edges:
            
            redge, created = models.RelationCategory.objects.update_or_create(
                age_name=edge.age_name,
                ontology=item,
                defaults=dict(
                    description=edge.description or "",
                    purl=edge.purl or "",
                    left=models.Expression.objects.get(age_name=edge.source, ontology=item),
                    right=models.Expression.objects.get(age_name=edge.target, ontology=item),
                ),
            )
            
            if created:
                print("Created new relation edge")
                
        for edge in step_edges:
            
            sedge, created = models.StepCategory.objects.update_or_create(
                age_name=edge.age_name,
                ontology=item,
                defaults=dict(
                    template=models.ProtocolStepTemplate.objects.get(id=edge.template),
                    left=models.Expression.objects.get(age_name=edge.source, ontology=item),
                    right=models.Expression.objects.get(age_name=edge.target, ontology=item),
                ),
            )
            
            if created:
                print("Created new step edge")
                
        

        print("Running Cleanup")
        models.StructureCategory.objects.filter(ontology=item).exclude(age_name__in=node_age_names).delete()
        models.GenericCategory.objects.filter(ontology=item).exclude(age_name__in=node_age_names).delete()
        models.MeasurementCategory.objects.filter(ontology=item).exclude(age_name__in=edge_age_names).delete()
        models.RelationCategory.objects.filter(ontology=item).exclude(age_name__in=edge_age_names).delete()
        models.StepCategory.objects.filter(ontology=item).exclude(age_name__in=edge_age_names).delete()
            
            
        
        
    
    else:
        if input.nodes:
            raise Exception("You must provide both nodes and edges if you provide any")
        if input.edges:
            raise Exception("You must provide both nodes and edges if you provide any")    
        
    
    
    

    return item


def delete_ontology(
    info: Info,
    input: DeleteOntologyInput,
) -> strawberry.ID:
    item = models.Ontology.objects.get(id=input.id)
    item.delete()

    return input.id
