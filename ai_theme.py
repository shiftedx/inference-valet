"""Folded-V design tokens; BRANDING.md defines their intended use.

Keep surface and interaction colors semantic so every Valet window shares one
identity. Legacy color names remain aliases for external/older integrations.
"""
THEME = {
    'bg': '#26212F',
    'card': '#302A39',
    'raised': '#3A3244',
    'line': '#514657',
    'text': '#FFF1D9',
    'muted': '#C0B4C8',
    'accent': '#ED794D',
    'primary': '#ED794D',
    'primary_hover': '#FF9167',
    'on_primary': '#26212F',
    'on_accent': '#26212F',
    'focus': '#FFB596',
    'selected': '#503B3B',
    'success': '#A9C8AB',
    'warning': '#E5BE7E',
    'error': '#EF9A9A',
    'info': '#BFB2CF',
    'chart_output': '#ED794D',
    'chart_gpu': '#A9C8AB',
    'chart_cpu': '#BFB2CF',
    'chart_output_fill': '#41303B',
    'chart_gpu_fill': '#2F3A37',
    'chart_cpu_fill': '#383041',
    'meter_gpu': '#ED794D',
    'meter_ram': '#DCC8AF',
}
# Compatibility only. New UI uses roles above, never a pigment as a role.
THEME.update(blue=THEME['accent'], teal=THEME['success'],
             violet=THEME['info'], amber=THEME['warning'],
             green=THEME['success'])

FONT_SIZES = {'caption': 9, 'body': 10, 'heading': 12, 'metric': 12}


def ui_font(role='body', bold=False):
    return ('Segoe UI', FONT_SIZES[role], 'bold' if bold else 'normal')
