from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings




@strawberry.input(description="Input for creating a new expression")
class PlotViewInput:
    plot: strawberry.ID
    view: strawberry.ID
    


def create_plot_view(
    info: Info,
    input: PlotViewInput,
) -> types.PlotView:


    
    graph_view, _ = models.PlotView.objects.get_or_create(
        view=models.GraphView.objects.get(id=input.view),
        plot=models.ScatterPlot.objects.get(id=input.plot),
        creator = info.context.request.user,
    )

    

    return graph_view