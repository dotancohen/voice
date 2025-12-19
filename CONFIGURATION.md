# Configuration Reference

Voice Rewrite stores its configuration in a JSON file located at `~/.config/voicerewrite/config.json`. The configuration directory can be customized via the `--config-dir` CLI argument.

See also: Quick reference in [README.md](../README.md#configuration)

## Configuration File Location

- **Default**: `~/.config/voicerewrite/config.json`
- **Custom**: Use `--config-dir /path/to/dir` when launching the application

If the configuration file doesn't exist, it will be created with default values on first run.

## Configuration Options

### database_file

**Type**: `string` (file path)
**Default**: `~/.config/voicerewrite/notes.db`

Path to the SQLite database file that stores notes and tags.

```json
{
  "database_file": "/home/user/.config/voicerewrite/notes.db"
}
```

### default_interface

**Type**: `string`
**Default**: `"gui"`
**Options**: `"gui"`, `"cli"`, `"tui"`, `"web"`

The default interface to launch when no subcommand is specified.

```json
{
  "default_interface": "gui"
}
```

### window_geometry

**Type**: `object` or `null`
**Default**: `null`

Stores the GUI window position and size for session persistence. Automatically updated when the GUI window is moved or resized.

```json
{
  "window_geometry": {
    "x": 100,
    "y": 100,
    "width": 1200,
    "height": 800
  }
}
```

### implementations

**Type**: `object`
**Default**: `{}`

Reserved for future use. Will store component implementation selections for pluggable architecture.

```json
{
  "implementations": {}
}
```

### themes

**Type**: `object`
**Default**: See below

Contains theming configuration for the application interfaces.

```json
{
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue"
    }
  }
}
```

#### themes.colours.warnings

**Type**: `string` (CSS color)
**Default**: `"#FFFF00"` (yellow)

Color used to highlight ambiguous tags in the GUI and TUI. Ambiguous tags are those with the same name but different parent hierarchies (e.g., `France/Paris` and `Texas/Paris`).

For light themes, consider using `"#FF8C00"` (dark orange) for better visibility.

#### themes.colours.tui_border_focused

**Type**: `string` (Textual color name or hex)
**Default**: `"green"`

Border color for the currently focused pane in the TUI (Terminal User Interface).

Accepts Textual color names (e.g., `"green"`, `"blue"`, `"red"`) or hex colors (e.g., `"#00FF00"`).

#### themes.colours.tui_border_unfocused

**Type**: `string` (Textual color name or hex)
**Default**: `"blue"`

Border color for unfocused panes in the TUI.

Accepts Textual color names or hex colors.

## Example Complete Configuration

```json
{
  "database_file": "/home/user/.config/voicerewrite/notes.db",
  "default_interface": "gui",
  "window_geometry": null,
  "implementations": {},
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue"
    }
  }
}
```

## Theme-Specific Warning Colors

The application supports theme-specific warning colors. If you want different warning colors for light and dark themes, you can use:

```json
{
  "themes": {
    "colours": {
      "warnings_dark": "#FFFF00",
      "warnings_light": "#FF8C00"
    }
  }
}
```

Note: If a generic `warnings` key is present, it takes precedence over theme-specific keys for backward compatibility.

## Modifying Configuration

Configuration can be modified by:

1. **Editing the JSON file directly** - Changes take effect on next application launch
2. **Using the application** - Some settings (like `window_geometry`) are automatically updated

The application validates configuration on load. If the JSON is malformed, default values will be used and a warning will be logged.
