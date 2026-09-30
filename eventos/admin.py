from django.contrib import admin
from .models import Evento, Sector, Artista, Recinto, Usuario, Orden, EntradaComprada

# Permite crear o editar los Sectores (Cancha, VIP, etc.) directamente dentro del Evento
class SectorInline(admin.TabularInline):
    model = Sector
    extra = 1

class EventoAdmin(admin.ModelAdmin):
    inlines = [SectorInline]
    list_display = ('nombre', 'fecha_hora', 'artista', 'recinto')
    search_fields = ('nombre', 'artista__nombre')
    list_filter = ('recinto',)

# Registramos todos los modelos para que el administrador pueda gestionarlos
admin.site.register(Evento, EventoAdmin)
admin.site.register(Artista)
admin.site.register(Recinto)
admin.site.register(Usuario)
admin.site.register(Orden)
admin.site.register(EntradaComprada)