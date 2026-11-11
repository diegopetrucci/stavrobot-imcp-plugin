# iMCP tools

**Source-derived from upstream iMCP tag `1.8.3`** (commit `6284060d73a5`), generated on **2026-11-11** from the Swift service tool definitions in a read-only clone of `github.com/mattt/iMCP`. On 2026-11-11 the 50 tools exposed by the operator's installed 1.8.3 were verified against a live probe (names, descriptions, and schemas match after this correction). The Home (requires iMCP Helper), Voicemail, and Voice Memos tools were not exposed on that Mac and remain source-derived only.

Supported deployments require iMCP **>=1.8.2** and use the bundled `imcp-server` over stdio. Before changing an allowlist, refresh or verify this list by running `scripts/probe_imcp.py` against the installed app: the live `tools/list` is authoritative. In particular, Voicemail is only exposed on macOS versions where upstream's `VoicemailService.isSupported` is true, Weather only in builds with WeatherKit available, and Home only when the iMCP Helper is paired; any service the operator has not enabled is absent from a live listing.

Scope of this document: 84 tools across Calendar, Capture, Contacts, Home, Location, Mail, Maps, Messages, Music, Notes, Phone, Reminders, Shortcuts, Utilities, Voicemail, Voice Memos, and Weather. Only tool names, descriptions, and input schemas are recorded (tool annotations are omitted); no tool was invoked and no tool result or personal data was captured. Schemas are rendered as JSON with sorted keys from the upstream JSONSchema definitions; enum values and numeric defaults that upstream derives from Swift enums or constants are expanded. Tools are listed alphabetically by name; tier guidance is in `DEPLOY.md` §2.1.

```json
[
  {
    "description": "Move accessories to a room. Return one result per accessory.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "accessories": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        },
        "room": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "room",
        "accessories"
      ],
      "type": "object"
    },
    "name": "accessories_assign_room"
  },
  {
    "description": "Inspect an accessory and its characteristics.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "accessory": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        },
        "include_values": {
          "default": false,
          "description": "Read live values. Defaults to false; unreachable devices return per-item errors.",
          "type": "boolean"
        }
      },
      "required": [
        "accessory"
      ],
      "type": "object"
    },
    "name": "accessories_get"
  },
  {
    "description": "Ask an accessory to identify itself with a light or sound.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "accessory": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "accessory"
      ],
      "type": "object"
    },
    "name": "accessories_identify"
  },
  {
    "description": "List accessories with room, bridge, reachability, and service information.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "bridged": {
          "type": "boolean"
        },
        "category": {
          "type": "string"
        },
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        },
        "in_default_room": {
          "type": "boolean"
        },
        "name_contains": {
          "type": "string"
        },
        "reachable": {
          "type": "boolean"
        },
        "room": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "accessories_list"
  },
  {
    "description": "Remove an accessory from its home. Pairing is required to add it again.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "accessory": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "accessory"
      ],
      "type": "object"
    },
    "name": "accessories_remove"
  },
  {
    "description": "Rename an accessory.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "accessory": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        },
        "name": {
          "type": "string"
        }
      },
      "required": [
        "accessory",
        "name"
      ],
      "type": "object"
    },
    "name": "accessories_rename"
  },
  {
    "description": "Create an enabled automation for a timer, characteristic value, sunrise, or sunset. Timer recurrence is daily or weekday numbers (1 Sunday through 7 Saturday).",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        },
        "name": {
          "type": "string"
        },
        "scenes": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        },
        "trigger": {
          "anyOf": [
            {
              "additionalProperties": false,
              "properties": {
                "fire_at": {
                  "description": "Future ISO 8601 timestamp on a whole-minute boundary, with a time zone.",
                  "format": "date-time",
                  "type": "string"
                },
                "recurrence": {
                  "anyOf": [
                    {
                      "enum": [
                        "daily"
                      ],
                      "type": "string"
                    },
                    {
                      "items": {
                        "maximum": 7,
                        "minimum": 1,
                        "type": "integer"
                      },
                      "minItems": 1,
                      "type": "array",
                      "uniqueItems": true
                    }
                  ]
                }
              },
              "required": [
                "fire_at"
              ],
              "type": "object"
            },
            {
              "additionalProperties": false,
              "properties": {
                "characteristic": {
                  "description": "HomeKit uniqueIdentifier UUID",
                  "type": "string"
                },
                "value": {
                  "anyOf": [
                    {
                      "type": "boolean"
                    },
                    {
                      "type": "number"
                    },
                    {
                      "type": "string"
                    }
                  ]
                }
              },
              "required": [
                "characteristic",
                "value"
              ],
              "type": "object"
            },
            {
              "additionalProperties": false,
              "properties": {
                "event": {
                  "enum": [
                    "sunrise",
                    "sunset"
                  ],
                  "type": "string"
                },
                "offset_minutes": {
                  "type": "integer"
                }
              },
              "required": [
                "event"
              ],
              "type": "object"
            }
          ]
        }
      },
      "required": [
        "name",
        "scenes",
        "trigger"
      ],
      "type": "object"
    },
    "name": "automations_create"
  },
  {
    "description": "List automation data exposed by HomeKit. Shortcuts and some Home app conditions may be incomplete. lastFireDate is unavailable.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "automations_list"
  },
  {
    "description": "Remove an automation from the home.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "automation": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "automation"
      ],
      "type": "object"
    },
    "name": "automations_remove"
  },
  {
    "description": "Rename an automation or change whether it is enabled.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "automation": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        },
        "enabled": {
          "type": "boolean"
        },
        "name": {
          "type": "string"
        }
      },
      "required": [
        "automation"
      ],
      "type": "object"
    },
    "name": "automations_update"
  },
  {
    "description": "List available calendars",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "calendars_list"
  },
  {
    "description": "Record audio with the device microphone",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "duration": {
          "default": 10,
          "description": "Recording duration in seconds",
          "maximum": 300,
          "minimum": 1,
          "type": "number"
        },
        "format": {
          "default": "mp4",
          "enum": [
            "mp4",
            "caf"
          ],
          "type": "string"
        },
        "quality": {
          "default": "medium",
          "description": "Audio quality",
          "enum": [
            "low",
            "medium",
            "high"
          ],
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "capture_record_audio"
  },
  {
    "description": "Take a picture with the device camera",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "autoExposure": {
          "default": true,
          "description": "Enable automatic exposure and light balancing",
          "type": "boolean"
        },
        "autoFocus": {
          "default": true,
          "description": "Enable automatic focus",
          "type": "boolean"
        },
        "autoWhiteBalance": {
          "default": true,
          "description": "Enable automatic white balance",
          "type": "boolean"
        },
        "delay": {
          "default": 1,
          "description": "Delay before taking photo, in seconds",
          "maximum": 60,
          "minimum": 0,
          "type": "number"
        },
        "device": {
          "default": "built-in",
          "description": "Camera device type",
          "enum": [
            "built-in",
            "continuity",
            "external",
            "desk-view"
          ],
          "type": "string"
        },
        "flash": {
          "default": "auto",
          "description": "Flash mode",
          "enum": [
            "auto",
            "on",
            "off"
          ],
          "type": "string"
        },
        "format": {
          "default": "jpeg",
          "enum": [
            "jpeg",
            "png"
          ],
          "type": "string"
        },
        "position": {
          "default": "unspecified",
          "description": "Camera position",
          "enum": [
            "unspecified",
            "back",
            "front"
          ],
          "type": "string"
        },
        "preset": {
          "default": "photo",
          "description": "Camera quality preset",
          "enum": [
            "photo",
            "low",
            "medium",
            "high",
            "hd1280x720",
            "hd1920x1080",
            "hd4K3840x2160"
          ],
          "type": "string"
        },
        "quality": {
          "default": 0.8,
          "description": "JPEG quality",
          "maximum": 1,
          "minimum": 0,
          "type": "number"
        }
      },
      "type": "object"
    },
    "name": "capture_take_picture"
  },
  {
    "description": "Take a screenshot of the screen, window, or application",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "bundleId": {
          "description": "Bundle ID for application capture (optional)",
          "type": "string"
        },
        "contentType": {
          "default": "display",
          "description": "Type of content to capture",
          "enum": [
            "display",
            "window",
            "application"
          ],
          "type": "string"
        },
        "displayId": {
          "description": "Display ID for display capture (optional)",
          "minimum": 0,
          "type": "number"
        },
        "format": {
          "default": "png",
          "enum": [
            "png",
            "jpeg"
          ],
          "type": "string"
        },
        "includesCursor": {
          "default": true,
          "description": "Include cursor in screenshot",
          "type": "boolean"
        },
        "quality": {
          "default": "medium",
          "description": "Screenshot quality and resolution",
          "enum": [
            "low",
            "medium",
            "high",
            "max"
          ],
          "type": "string"
        },
        "windowId": {
          "description": "Window ID for window capture (optional)",
          "minimum": 0,
          "type": "number"
        }
      },
      "type": "object"
    },
    "name": "capture_take_screenshot"
  },
  {
    "description": "Read live characteristic values with one result per UUID.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "characteristics": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "characteristics"
      ],
      "type": "object"
    },
    "name": "characteristics_read"
  },
  {
    "description": "Write a characteristic value after checking its format and limits. Data values use base64 strings.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "characteristic": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        },
        "value": {
          "anyOf": [
            {
              "type": "boolean"
            },
            {
              "type": "number"
            },
            {
              "type": "string"
            }
          ]
        }
      },
      "required": [
        "characteristic",
        "value"
      ],
      "type": "object"
    },
    "name": "characteristics_write"
  },
  {
    "description": "Create a new contact with the specified information.",
    "inputSchema": {
      "properties": {
        "birthday": {
          "properties": {
            "day": {
              "maximum": 31,
              "minimum": 1,
              "type": "integer"
            },
            "month": {
              "maximum": 12,
              "minimum": 1,
              "type": "integer"
            },
            "year": {
              "type": "integer"
            }
          },
          "required": [
            "day",
            "month"
          ],
          "type": "object"
        },
        "emailAddresses": {
          "additionalProperties": true,
          "properties": {
            "home": {
              "type": "string"
            },
            "work": {
              "type": "string"
            }
          },
          "type": "object"
        },
        "familyName": {
          "type": "string"
        },
        "givenName": {
          "type": "string"
        },
        "jobTitle": {
          "type": "string"
        },
        "organizationName": {
          "type": "string"
        },
        "phoneNumbers": {
          "additionalProperties": true,
          "properties": {
            "home": {
              "type": "string"
            },
            "mobile": {
              "type": "string"
            },
            "work": {
              "type": "string"
            }
          },
          "type": "object"
        },
        "postalAddresses": {
          "additionalProperties": true,
          "properties": {
            "home": {
              "properties": {
                "city": {
                  "type": "string"
                },
                "country": {
                  "type": "string"
                },
                "postalCode": {
                  "type": "string"
                },
                "state": {
                  "type": "string"
                },
                "street": {
                  "type": "string"
                }
              },
              "type": "object"
            },
            "work": {
              "properties": {
                "city": {
                  "type": "string"
                },
                "country": {
                  "type": "string"
                },
                "postalCode": {
                  "type": "string"
                },
                "state": {
                  "type": "string"
                },
                "street": {
                  "type": "string"
                }
              },
              "type": "object"
            }
          },
          "type": "object"
        }
      },
      "required": [
        "givenName"
      ],
      "type": "object"
    },
    "name": "contacts_create"
  },
  {
    "description": "List contacts in a stable order. Returns every contact by default; use limit and offset to page through large address books.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "limit": {
          "description": "Maximum number of contacts to return",
          "minimum": 1,
          "type": "integer"
        },
        "offset": {
          "default": 0,
          "description": "Number of contacts to skip, in the same stable order",
          "minimum": 0,
          "type": "integer"
        }
      },
      "type": "object"
    },
    "name": "contacts_list"
  },
  {
    "description": "Get contact information about the user, including name, phone number, email, birthday, relations, address, online presence, and occupation. Always run this tool when the user asks a question that requires personal information about themselves.",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "contacts_me"
  },
  {
    "description": "Search contacts by name, phone number, and/or email",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "email": {
          "description": "Email address to search for",
          "type": "string"
        },
        "name": {
          "description": "Name to search for",
          "type": "string"
        },
        "phone": {
          "description": "Phone number to search for",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "contacts_search"
  },
  {
    "description": "Update an existing contact's information. Only provide values for properties that need to be changed; omit any properties that should remain unchanged. Reading or changing contact notes is not supported.",
    "inputSchema": {
      "properties": {
        "birthday": {
          "properties": {
            "day": {
              "maximum": 31,
              "minimum": 1,
              "type": "integer"
            },
            "month": {
              "maximum": 12,
              "minimum": 1,
              "type": "integer"
            },
            "year": {
              "type": "integer"
            }
          },
          "required": [
            "day",
            "month"
          ],
          "type": "object"
        },
        "emailAddresses": {
          "additionalProperties": true,
          "properties": {
            "home": {
              "type": "string"
            },
            "work": {
              "type": "string"
            }
          },
          "type": "object"
        },
        "familyName": {
          "type": "string"
        },
        "givenName": {
          "type": "string"
        },
        "identifier": {
          "description": "Unique identifier of the contact to update",
          "type": "string"
        },
        "jobTitle": {
          "type": "string"
        },
        "organizationName": {
          "type": "string"
        },
        "phoneNumbers": {
          "additionalProperties": true,
          "properties": {
            "home": {
              "type": "string"
            },
            "mobile": {
              "type": "string"
            },
            "work": {
              "type": "string"
            }
          },
          "type": "object"
        },
        "postalAddresses": {
          "additionalProperties": true,
          "properties": {
            "home": {
              "properties": {
                "city": {
                  "type": "string"
                },
                "country": {
                  "type": "string"
                },
                "postalCode": {
                  "type": "string"
                },
                "state": {
                  "type": "string"
                },
                "street": {
                  "type": "string"
                }
              },
              "type": "object"
            },
            "work": {
              "properties": {
                "city": {
                  "type": "string"
                },
                "country": {
                  "type": "string"
                },
                "postalCode": {
                  "type": "string"
                },
                "state": {
                  "type": "string"
                },
                "street": {
                  "type": "string"
                }
              },
              "type": "object"
            }
          },
          "type": "object"
        }
      },
      "required": [
        "identifier"
      ],
      "type": "object"
    },
    "name": "contacts_update"
  },
  {
    "description": "Create a new calendar event with specified properties",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "alarms": {
          "description": "Alarm configurations for the event",
          "items": {
            "anyOf": [
              {
                "additionalProperties": false,
                "properties": {
                  "emailAddress": {
                    "description": "Email address to send notification to",
                    "type": "string"
                  },
                  "minutes": {
                    "description": "Minutes before the event start (negative for after the event start)",
                    "type": "integer"
                  },
                  "sound": {
                    "description": "Sound name to play when alarm triggers",
                    "enum": [
                      "Basso",
                      "Blow",
                      "Bottle",
                      "Frog",
                      "Funk",
                      "Glass",
                      "Hero",
                      "Morse",
                      "Ping",
                      "Pop",
                      "Purr",
                      "Sosumi",
                      "Submarine",
                      "Tink"
                    ],
                    "type": "string"
                  },
                  "type": {
                    "const": "relative",
                    "type": "string"
                  }
                },
                "required": [
                  "minutes"
                ],
                "type": "object"
              },
              {
                "additionalProperties": false,
                "properties": {
                  "datetime": {
                    "description": "Alarm date/time. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
                    "format": "date-time",
                    "type": "string"
                  },
                  "emailAddress": {
                    "description": "Email address to send notification to",
                    "type": "string"
                  },
                  "sound": {
                    "description": "Sound name to play when alarm triggers",
                    "enum": [
                      "Basso",
                      "Blow",
                      "Bottle",
                      "Frog",
                      "Funk",
                      "Glass",
                      "Hero",
                      "Morse",
                      "Ping",
                      "Pop",
                      "Purr",
                      "Sosumi",
                      "Submarine",
                      "Tink"
                    ],
                    "type": "string"
                  },
                  "type": {
                    "const": "absolute",
                    "type": "string"
                  }
                },
                "required": [
                  "type",
                  "datetime"
                ],
                "type": "object"
              },
              {
                "additionalProperties": false,
                "properties": {
                  "emailAddress": {
                    "description": "Email address to send notification to",
                    "type": "string"
                  },
                  "latitude": {
                    "maximum": 90,
                    "minimum": -90,
                    "type": "number"
                  },
                  "locationTitle": {
                    "type": "string"
                  },
                  "longitude": {
                    "maximum": 180,
                    "minimum": -180,
                    "type": "number"
                  },
                  "proximity": {
                    "default": "enter",
                    "description": "Proximity trigger type",
                    "enum": [
                      "enter",
                      "leave"
                    ],
                    "type": "string"
                  },
                  "radius": {
                    "description": "Radius in meters. Omit to use the system default.",
                    "minimum": 0,
                    "type": "number"
                  },
                  "sound": {
                    "description": "Sound name to play when alarm triggers",
                    "enum": [
                      "Basso",
                      "Blow",
                      "Bottle",
                      "Frog",
                      "Funk",
                      "Glass",
                      "Hero",
                      "Morse",
                      "Ping",
                      "Pop",
                      "Purr",
                      "Sosumi",
                      "Submarine",
                      "Tink"
                    ],
                    "type": "string"
                  },
                  "type": {
                    "const": "proximity",
                    "type": "string"
                  }
                },
                "required": [
                  "type",
                  "locationTitle",
                  "latitude",
                  "longitude"
                ],
                "type": "object"
              }
            ]
          },
          "type": "array"
        },
        "availability": {
          "default": "busy",
          "description": "Availability status",
          "enum": [
            "busy",
            "free",
            "tentative",
            "unavailable"
          ],
          "type": "string"
        },
        "calendar": {
          "description": "Calendar to use (uses default if not specified)",
          "type": "string"
        },
        "end": {
          "description": "End date/time for the event. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "hasAlarms": {
          "type": "boolean"
        },
        "isAllDay": {
          "default": false,
          "type": "boolean"
        },
        "isRecurring": {
          "type": "boolean"
        },
        "location": {
          "type": "string"
        },
        "notes": {
          "type": "string"
        },
        "start": {
          "description": "Start date/time for the event. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "title": {
          "type": "string"
        },
        "url": {
          "format": "uri",
          "type": "string"
        }
      },
      "required": [
        "title",
        "start",
        "end"
      ],
      "type": "object"
    },
    "name": "events_create"
  },
  {
    "description": "Delete a calendar event by identifier. For a recurring event, pass the start date of the occurrence to delete.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "identifier": {
          "description": "The event identifier",
          "type": "string"
        },
        "span": {
          "default": "thisEvent",
          "description": "For recurring events: delete only this occurrence, or this and all future events",
          "enum": [
            "thisEvent",
            "futureEvents"
          ],
          "type": "string"
        },
        "start": {
          "description": "Start date of the occurrence to delete (ISO 8601). Required for recurring events, since every occurrence shares the same identifier.",
          "type": "string"
        }
      },
      "required": [
        "identifier"
      ],
      "type": "object"
    },
    "name": "events_delete"
  },
  {
    "description": "Get events from the calendar with flexible filtering options",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "availability": {
          "description": "Filter by availability status",
          "enum": [
            "busy",
            "free",
            "tentative",
            "unavailable"
          ],
          "type": "string"
        },
        "calendars": {
          "description": "Names of calendars to fetch from; if empty, fetches from all calendars",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "end": {
          "description": "End date/time (defaults to one week from start; one day if start is date-only). If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "hasAlarms": {
          "type": "boolean"
        },
        "includeAllDay": {
          "default": true,
          "type": "boolean"
        },
        "isRecurring": {
          "type": "boolean"
        },
        "query": {
          "description": "Text to search for in event titles and locations",
          "type": "string"
        },
        "start": {
          "description": "Start date/time (defaults to now; if end is date-only and start is omitted, uses end's local midnight). If timezone is omitted, local time is assumed.",
          "format": "date-time",
          "type": "string"
        },
        "status": {
          "description": "Filter by event status",
          "enum": [
            "none",
            "tentative",
            "confirmed",
            "canceled"
          ],
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "events_fetch"
  },
  {
    "description": "Update an existing calendar event. Only provide values for properties that need to be changed; omit any properties that should remain unchanged. Passing null clears title, location, notes, url, or alarms. For a recurring event, pass the start date of the occurrence to update.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "alarms": {
          "anyOf": [
            {
              "description": "Alarm configurations for the event, replacing any existing alarms. Pass null to remove all alarms.",
              "items": {
                "anyOf": [
                  {
                    "additionalProperties": false,
                    "properties": {
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "minutes": {
                        "description": "Minutes before the event start (negative for after the event start)",
                        "type": "integer"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "relative",
                        "type": "string"
                      }
                    },
                    "required": [
                      "minutes"
                    ],
                    "type": "object"
                  },
                  {
                    "additionalProperties": false,
                    "properties": {
                      "datetime": {
                        "description": "Alarm date/time. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
                        "format": "date-time",
                        "type": "string"
                      },
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "absolute",
                        "type": "string"
                      }
                    },
                    "required": [
                      "type",
                      "datetime"
                    ],
                    "type": "object"
                  },
                  {
                    "additionalProperties": false,
                    "properties": {
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "latitude": {
                        "maximum": 90,
                        "minimum": -90,
                        "type": "number"
                      },
                      "locationTitle": {
                        "type": "string"
                      },
                      "longitude": {
                        "maximum": 180,
                        "minimum": -180,
                        "type": "number"
                      },
                      "proximity": {
                        "default": "enter",
                        "description": "Proximity trigger type",
                        "enum": [
                          "enter",
                          "leave"
                        ],
                        "type": "string"
                      },
                      "radius": {
                        "description": "Radius in meters. Omit to use the system default.",
                        "minimum": 0,
                        "type": "number"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "proximity",
                        "type": "string"
                      }
                    },
                    "required": [
                      "type",
                      "locationTitle",
                      "latitude",
                      "longitude"
                    ],
                    "type": "object"
                  }
                ]
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ]
        },
        "availability": {
          "description": "Availability status",
          "enum": [
            "busy",
            "free",
            "tentative",
            "unavailable"
          ],
          "type": "string"
        },
        "calendar": {
          "description": "Calendar to move the event to, matched by title",
          "type": "string"
        },
        "end": {
          "description": "New end date/time for the event. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "identifier": {
          "description": "The event identifier",
          "type": "string"
        },
        "isAllDay": {
          "description": "Whether the event spans the whole day",
          "type": "boolean"
        },
        "location": {
          "anyOf": [
            {
              "description": "Location text. Pass null to clear.",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "notes": {
          "anyOf": [
            {
              "description": "Event notes. Pass null to clear.",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "occurrence": {
          "description": "Start date of the occurrence to update, since every occurrence of a recurring event shares the same identifier. Required for recurring events.",
          "format": "date-time",
          "type": "string"
        },
        "span": {
          "default": "thisEvent",
          "description": "For recurring events: update only this occurrence, or this and all future events",
          "enum": [
            "thisEvent",
            "futureEvents"
          ],
          "type": "string"
        },
        "start": {
          "description": "New start date/time for the event. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "title": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "url": {
          "anyOf": [
            {
              "description": "URL attached to the event. Pass null to clear.",
              "format": "uri",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "identifier"
      ],
      "type": "object"
    },
    "name": "events_update"
  },
  {
    "description": "Export rooms, zones, accessories, services, characteristic metadata, scenes, and exposed automations.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        },
        "include_values": {
          "default": false,
          "description": "Read live values. Defaults to false; unreachable devices return per-item errors.",
          "type": "boolean"
        }
      },
      "type": "object"
    },
    "name": "home_export"
  },
  {
    "description": "List homes, counts, primary home, and authorization status.",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "homes_list"
  },
  {
    "description": "Get the user's current location",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "location_current"
  },
  {
    "description": "Convert a postal address to geographic coordinates.\nPlace names can resolve to unrelated street addresses.\nUse maps_search for place names, businesses, and landmarks.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "address": {
          "description": "Postal address to geocode",
          "type": "string"
        }
      },
      "required": [
        "address"
      ],
      "type": "object"
    },
    "name": "location_geocode"
  },
  {
    "description": "Convert geographic coordinates to an address",
    "inputSchema": {
      "properties": {
        "latitude": {
          "type": "number"
        },
        "longitude": {
          "type": "number"
        }
      },
      "required": [
        "latitude",
        "longitude"
      ],
      "type": "object"
    },
    "name": "location_reverse-geocode"
  },
  {
    "description": "Open a compose URL in the default email app. Does not save or send a message.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "bcc": {
          "description": "Comma-separated BCC addresses",
          "type": "string"
        },
        "body": {
          "description": "Plain-text body",
          "type": "string"
        },
        "cc": {
          "description": "Comma-separated CC addresses",
          "type": "string"
        },
        "subject": {
          "type": "string"
        },
        "to": {
          "description": "Comma-separated recipient addresses",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "mail_compose"
  },
  {
    "description": "List mailboxes in the local Mail index. Use each @id as the mailbox search filter. Account email is included when available. Requires folder access.",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "mail_mailboxes_list"
  },
  {
    "description": "Read local MIME content by a returned message identifier. HTML is returned as labeled data; remote content is never loaded. Attachments are listed without their content; isStoredSeparately marks parts that Mail keeps outside the message file.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "description": "Message identifier from mail_messages_search",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "mail_messages_read"
  },
  {
    "description": "Search local sender and subject metadata. Filters combine with AND; newest first. To get the next page, pass nextCursor as cursor with the same filters. Does not search bodies or download messages. Sync status is unknown; empty results do not prove the server mailbox is empty.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "cursor": {
          "description": "The nextCursor value from a previous search with the same filters",
          "type": "string"
        },
        "end": {
          "description": "End of the date range (exclusive). If timezone is omitted, local time is assumed. A date-only value includes that whole local day.",
          "format": "date-time",
          "type": "string"
        },
        "isRead": {
          "description": "If true, fetch read messages; if false, unread; if omitted, fetch all",
          "type": "boolean"
        },
        "limit": {
          "default": 30,
          "description": "Maximum messages to return",
          "maximum": 100,
          "minimum": 1,
          "type": "integer"
        },
        "mailbox": {
          "description": "The @id string from mail_mailboxes_list, for example \"V10:12\". Do not use the url field.",
          "type": "string"
        },
        "sender": {
          "description": "Sender address substring",
          "type": "string"
        },
        "start": {
          "description": "Start of the date range (inclusive). If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "subject": {
          "description": "Subject substring",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "mail_messages_search"
  },
  {
    "description": "Get automobile or walking directions between two locations.\nUse maps_eta for a transit travel-time estimate.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "destinationAddress": {
          "description": "Destination address",
          "type": "string"
        },
        "destinationCoordinates": {
          "additionalProperties": false,
          "description": "Destination coordinates",
          "properties": {
            "latitude": {
              "type": "number"
            },
            "longitude": {
              "type": "number"
            }
          },
          "required": [
            "latitude",
            "longitude"
          ],
          "type": "object"
        },
        "originAddress": {
          "description": "Origin address",
          "type": "string"
        },
        "originCoordinates": {
          "additionalProperties": false,
          "description": "Origin coordinates",
          "properties": {
            "latitude": {
              "type": "number"
            },
            "longitude": {
              "type": "number"
            }
          },
          "required": [
            "latitude",
            "longitude"
          ],
          "type": "object"
        },
        "transportType": {
          "default": "automobile",
          "description": "Transport type for the route",
          "enum": [
            "automobile",
            "walking",
            "any"
          ],
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "maps_directions"
  },
  {
    "description": "Calculate estimated travel time between two locations",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "destinationLatitude": {
          "type": "number"
        },
        "destinationLongitude": {
          "type": "number"
        },
        "originLatitude": {
          "type": "number"
        },
        "originLongitude": {
          "type": "number"
        },
        "transportType": {
          "default": "automobile",
          "description": "Transport type",
          "enum": [
            "automobile",
            "walking",
            "transit"
          ],
          "type": "string"
        }
      },
      "required": [
        "originLatitude",
        "originLongitude",
        "destinationLatitude",
        "destinationLongitude"
      ],
      "type": "object"
    },
    "name": "maps_eta"
  },
  {
    "description": "Find points of interest near a location",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "category": {
          "description": "POI category",
          "enum": [
            "airport",
            "restaurant",
            "gas",
            "parking",
            "hotel",
            "hospital",
            "police",
            "fire",
            "store",
            "museum",
            "park",
            "school",
            "library",
            "theater",
            "bank",
            "atm",
            "cafe",
            "pharmacy",
            "gym",
            "laundry"
          ],
          "type": "string"
        },
        "latitude": {
          "type": "number"
        },
        "limit": {
          "default": 10,
          "description": "Maximum results to return",
          "type": "integer"
        },
        "longitude": {
          "type": "number"
        },
        "radius": {
          "default": 5000,
          "description": "Search radius in meters",
          "type": "number"
        }
      },
      "required": [
        "category",
        "latitude",
        "longitude"
      ],
      "type": "object"
    },
    "name": "maps_explore"
  },
  {
    "description": "Generate a static map image for given coordinates and parameters",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "height": {
          "default": 1024,
          "description": "Image height in pixels",
          "type": "integer"
        },
        "latitude": {
          "type": "number"
        },
        "latitudeDelta": {
          "description": "Latitude degrees visible on map",
          "type": "number"
        },
        "longitude": {
          "type": "number"
        },
        "longitudeDelta": {
          "description": "Longitude degrees visible on map",
          "type": "number"
        },
        "mapType": {
          "default": "standard",
          "description": "Map type",
          "enum": [
            "standard",
            "satellite",
            "hybrid",
            "mutedStandard"
          ],
          "type": "string"
        },
        "showBuildings": {
          "default": false,
          "description": "Whether to show buildings",
          "type": "boolean"
        },
        "showPointsOfInterest": {
          "oneOf": [
            {
              "default": false,
              "description": "Show all (true) or no (false) POIs",
              "type": "boolean"
            },
            {
              "description": "Specific POI types to show",
              "items": {
                "anyOf": [
                  {
                    "const": "airport",
                    "type": "string"
                  },
                  {
                    "const": "restaurant",
                    "type": "string"
                  },
                  {
                    "const": "gas",
                    "type": "string"
                  },
                  {
                    "const": "parking",
                    "type": "string"
                  },
                  {
                    "const": "hotel",
                    "type": "string"
                  },
                  {
                    "const": "hospital",
                    "type": "string"
                  },
                  {
                    "const": "police",
                    "type": "string"
                  },
                  {
                    "const": "fire",
                    "type": "string"
                  },
                  {
                    "const": "store",
                    "type": "string"
                  },
                  {
                    "const": "museum",
                    "type": "string"
                  },
                  {
                    "const": "park",
                    "type": "string"
                  },
                  {
                    "const": "school",
                    "type": "string"
                  },
                  {
                    "const": "library",
                    "type": "string"
                  },
                  {
                    "const": "theater",
                    "type": "string"
                  },
                  {
                    "const": "bank",
                    "type": "string"
                  },
                  {
                    "const": "atm",
                    "type": "string"
                  },
                  {
                    "const": "cafe",
                    "type": "string"
                  },
                  {
                    "const": "pharmacy",
                    "type": "string"
                  },
                  {
                    "const": "gym",
                    "type": "string"
                  },
                  {
                    "const": "laundry",
                    "type": "string"
                  }
                ]
              },
              "minItems": 1,
              "type": "array"
            }
          ]
        },
        "width": {
          "default": 1024,
          "description": "Image width in pixels",
          "type": "integer"
        }
      },
      "required": [
        "latitude",
        "longitude",
        "latitudeDelta",
        "longitudeDelta"
      ],
      "type": "object"
    },
    "name": "maps_generate"
  },
  {
    "description": "Search for places, addresses, points of interest by text query",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "query": {
          "description": "Search text (place name, address, etc.)",
          "type": "string"
        },
        "region": {
          "additionalProperties": false,
          "description": "Region to bias search results",
          "properties": {
            "latitude": {
              "type": "number"
            },
            "longitude": {
              "type": "number"
            },
            "radius": {
              "default": 5000,
              "description": "Search radius in meters",
              "type": "number"
            }
          },
          "required": [
            "latitude",
            "longitude"
          ],
          "type": "object"
        }
      },
      "required": [
        "query"
      ],
      "type": "object"
    },
    "name": "maps_search"
  },
  {
    "description": "Read one attachment of a message, by the @id messages_fetch lists with attachments=true: the file, base64-encoded, with its name, type and size",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "description": "The attachment @id",
          "type": "string"
        },
        "maxBytes": {
          "default": 26214400,
          "description": "Refuse files larger than this",
          "maximum": 104857600,
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "messages_attachment_read"
  },
  {
    "description": "Fetch messages from the Messages app. Each message names the conversation it belongs to (isPartOf). The first message from each conversation includes its name and participants; later messages give only its @id.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "attachments": {
          "default": false,
          "description": "List each message's attachments (attachment: name, encodingFormat, contentSize, @id for messages_attachment_read) and include messages that carry attachments but no text",
          "type": "boolean"
        },
        "chatId": {
          "description": "Conversation @id, as reported in a message's isPartOf. Fetches only messages in that conversation",
          "type": "string"
        },
        "end": {
          "description": "End of the date range (exclusive). If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "isRead": {
          "description": "If true, fetch read messages; if false, unread incoming; if omitted, fetch all",
          "type": "boolean"
        },
        "limit": {
          "default": 30,
          "description": "Maximum messages to return",
          "type": "integer"
        },
        "participants": {
          "description": "Participant handles (phone or email). Phone numbers should use E.164 format",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "query": {
          "description": "Search term to filter messages by content",
          "type": "string"
        },
        "start": {
          "description": "Start of the date range (inclusive). If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "messages_fetch"
  },
  {
    "description": "Search the Apple Music catalog",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "includeTopResults": {
          "default": false,
          "description": "Include top results in the response",
          "type": "boolean"
        },
        "limit": {
          "default": 10,
          "description": "Maximum results per type",
          "maximum": 50,
          "minimum": 1,
          "type": "integer"
        },
        "offset": {
          "description": "Offset into the results",
          "minimum": 0,
          "type": "integer"
        },
        "term": {
          "description": "Search term",
          "type": "string"
        },
        "types": {
          "description": "Catalog types to include. Omit to search songs, albums, artists, and playlists.",
          "items": {
            "enum": [
              "songs",
              "albums",
              "artists",
              "playlists",
              "musicVideos",
              "stations",
              "topResults"
            ],
            "type": "string"
          },
          "minItems": 1,
          "type": "array"
        }
      },
      "required": [
        "term"
      ],
      "type": "object"
    },
    "name": "music_catalog_search"
  },
  {
    "description": "Control Music app playback using a single action parameter",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "action": {
          "enum": [
            "play",
            "pause",
            "playpause",
            "next",
            "previous",
            "stop",
            "seek"
          ],
          "type": "string"
        },
        "position": {
          "description": "Playback position in seconds (for seek). Clamped to the current track's duration, or to 86400 seconds when the duration is unknown.",
          "type": "number"
        }
      },
      "required": [
        "action"
      ],
      "type": "object"
    },
    "name": "music_control"
  },
  {
    "description": "Get currently playing track info from Music app",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "music_now_playing"
  },
  {
    "description": "Fetch notes from the Notes app, most recently edited first, with each note's title, preview, folder, and dates. Use notes_read for a note's full contents. Notes in Recently Deleted are left out unless that folder is requested. When more notes may match, the result has a nextCursor; pass it as cursor, with the same filters, to continue.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "cursor": {
          "description": "The nextCursor of a previous result, to fetch the notes after it",
          "type": "string"
        },
        "end": {
          "description": "End of the range of dates the notes were last edited (exclusive). If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "folder": {
          "description": "Name or @id of a folder, as returned by notes_folders. Fetches only the notes directly in that folder",
          "type": "string"
        },
        "limit": {
          "default": 30,
          "description": "Maximum notes to return",
          "maximum": 100,
          "minimum": 1,
          "type": "integer"
        },
        "query": {
          "description": "Text to search for in note titles and contents, including tags, tables, and text recognized in images (case-insensitive)",
          "type": "string"
        },
        "start": {
          "description": "Start of the range of dates the notes were last edited (inclusive). If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "notes_fetch"
  },
  {
    "description": "List the folders in the Notes app, with their accounts and how many notes each holds",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "notes_folders"
  },
  {
    "description": "Read the full contents of a note from the Notes app, as Markdown with headings, lists, checklists, links, and tables, or as plain text. Attachments such as images and drawings appear as bracketed descriptions. Notes locked with a password can't be read.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "format": {
          "default": "markdown",
          "description": "Format of the returned text",
          "enum": [
            "markdown",
            "plain"
          ],
          "type": "string"
        },
        "id": {
          "description": "The note @id, as returned by notes_fetch",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "notes_read"
  },
  {
    "description": "Start a phone call from the Mac (via iPhone). The system asks the user to confirm before dialing.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "phoneNumber": {
          "description": "Phone number to call. E.164 format is recommended. Digits, a leading +, and common formatting only; * and # are not supported.",
          "type": "string"
        }
      },
      "required": [
        "phoneNumber"
      ],
      "type": "object"
    },
    "name": "phone_call"
  },
  {
    "description": "Fetch phone call history from the Mac (synced from iPhone)",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "call_type": {
          "description": "Filter by call type, or omit for all",
          "enum": [
            "incoming",
            "outgoing",
            "missed"
          ],
          "type": "string"
        },
        "end": {
          "description": "End of the date range (exclusive). ISO 8601 format. If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "limit": {
          "default": 30,
          "description": "Maximum calls to return",
          "minimum": 1,
          "type": "integer"
        },
        "participant": {
          "description": "Phone number or contact name to filter by (partial match supported)",
          "type": "string"
        },
        "start": {
          "description": "Start of the date range (inclusive). ISO 8601 format. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "phone_calls_fetch"
  },
  {
    "description": "Create a new reminder with specified properties",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "alarms": {
          "anyOf": [
            {
              "description": "Alarm configurations for the reminder. Pass null to remove all alarms.",
              "items": {
                "anyOf": [
                  {
                    "description": "Minutes before the due date",
                    "type": "integer"
                  },
                  {
                    "additionalProperties": false,
                    "properties": {
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "minutes": {
                        "description": "Minutes offset from the due date (positive is before)",
                        "type": "integer"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "relative",
                        "type": "string"
                      }
                    },
                    "required": [
                      "minutes"
                    ],
                    "type": "object"
                  },
                  {
                    "additionalProperties": false,
                    "properties": {
                      "datetime": {
                        "description": "Alarm date/time. If timezone is omitted, local time is assumed.",
                        "format": "date-time",
                        "type": "string"
                      },
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "absolute",
                        "type": "string"
                      }
                    },
                    "required": [
                      "type",
                      "datetime"
                    ],
                    "type": "object"
                  },
                  {
                    "anyOf": [
                      {
                        "additionalProperties": false,
                        "properties": {
                          "emailAddress": {
                            "description": "Email address to send notification to",
                            "type": "string"
                          },
                          "location": {
                            "description": "Place name or address to trigger on, resolved with Maps",
                            "type": "string"
                          },
                          "proximity": {
                            "default": "enter",
                            "description": "Proximity trigger type",
                            "enum": [
                              "enter",
                              "leave"
                            ],
                            "type": "string"
                          },
                          "radius": {
                            "description": "Radius in meters. Omit to use the system default.",
                            "minimum": 0,
                            "type": "number"
                          },
                          "sound": {
                            "description": "Sound name to play when alarm triggers",
                            "enum": [
                              "Basso",
                              "Blow",
                              "Bottle",
                              "Frog",
                              "Funk",
                              "Glass",
                              "Hero",
                              "Morse",
                              "Ping",
                              "Pop",
                              "Purr",
                              "Sosumi",
                              "Submarine",
                              "Tink"
                            ],
                            "type": "string"
                          },
                          "type": {
                            "const": "proximity",
                            "type": "string"
                          }
                        },
                        "required": [
                          "type",
                          "location"
                        ],
                        "type": "object"
                      },
                      {
                        "additionalProperties": false,
                        "properties": {
                          "emailAddress": {
                            "description": "Email address to send notification to",
                            "type": "string"
                          },
                          "latitude": {
                            "maximum": 90,
                            "minimum": -90,
                            "type": "number"
                          },
                          "locationTitle": {
                            "type": "string"
                          },
                          "longitude": {
                            "maximum": 180,
                            "minimum": -180,
                            "type": "number"
                          },
                          "proximity": {
                            "default": "enter",
                            "description": "Proximity trigger type",
                            "enum": [
                              "enter",
                              "leave"
                            ],
                            "type": "string"
                          },
                          "radius": {
                            "description": "Radius in meters. Omit to use the system default.",
                            "minimum": 0,
                            "type": "number"
                          },
                          "sound": {
                            "description": "Sound name to play when alarm triggers",
                            "enum": [
                              "Basso",
                              "Blow",
                              "Bottle",
                              "Frog",
                              "Funk",
                              "Glass",
                              "Hero",
                              "Morse",
                              "Ping",
                              "Pop",
                              "Purr",
                              "Sosumi",
                              "Submarine",
                              "Tink"
                            ],
                            "type": "string"
                          },
                          "type": {
                            "const": "proximity",
                            "type": "string"
                          }
                        },
                        "required": [
                          "type",
                          "locationTitle",
                          "latitude",
                          "longitude"
                        ],
                        "type": "object"
                      }
                    ]
                  }
                ]
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ]
        },
        "due": {
          "anyOf": [
            {
              "description": "Due date/time for the reminder. If timezone is omitted, local time is assumed. Date-only uses local midnight. Pass null to clear.",
              "format": "date-time",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "list": {
          "description": "Reminder list name, or the identifier of one of several lists sharing a name. An unmatched name uses the default list.",
          "type": "string"
        },
        "notes": {
          "anyOf": [
            {
              "description": "Notes for the reminder. Pass null to clear.",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "priority": {
          "default": "none",
          "enum": [
            "none",
            "low",
            "medium",
            "high"
          ],
          "type": "string"
        },
        "recurrence": {
          "anyOf": [
            {
              "additionalProperties": false,
              "description": "Recurrence rule for a repeating reminder. Pass null to stop repeating.",
              "properties": {
                "daysOfTheMonth": {
                  "description": "Days of the month the reminder repeats on; nonzero, with negatives counting from the end (-1 is the last day)",
                  "items": {
                    "maximum": 31,
                    "minimum": -31,
                    "type": "integer"
                  },
                  "type": "array"
                },
                "daysOfTheWeek": {
                  "description": "Days of the week the reminder repeats on; prefix an ordinal (first through fifth, last, or second-to-last through fifth-to-last) to repeat on one weekday of the month, e.g. \"second tuesday\"",
                  "items": {
                    "enum": [
                      "sunday",
                      "monday",
                      "tuesday",
                      "wednesday",
                      "thursday",
                      "friday",
                      "saturday",
                      "first sunday",
                      "first monday",
                      "first tuesday",
                      "first wednesday",
                      "first thursday",
                      "first friday",
                      "first saturday",
                      "second sunday",
                      "second monday",
                      "second tuesday",
                      "second wednesday",
                      "second thursday",
                      "second friday",
                      "second saturday",
                      "third sunday",
                      "third monday",
                      "third tuesday",
                      "third wednesday",
                      "third thursday",
                      "third friday",
                      "third saturday",
                      "fourth sunday",
                      "fourth monday",
                      "fourth tuesday",
                      "fourth wednesday",
                      "fourth thursday",
                      "fourth friday",
                      "fourth saturday",
                      "fifth sunday",
                      "fifth monday",
                      "fifth tuesday",
                      "fifth wednesday",
                      "fifth thursday",
                      "fifth friday",
                      "fifth saturday",
                      "last sunday",
                      "last monday",
                      "last tuesday",
                      "last wednesday",
                      "last thursday",
                      "last friday",
                      "last saturday",
                      "second-to-last sunday",
                      "second-to-last monday",
                      "second-to-last tuesday",
                      "second-to-last wednesday",
                      "second-to-last thursday",
                      "second-to-last friday",
                      "second-to-last saturday",
                      "third-to-last sunday",
                      "third-to-last monday",
                      "third-to-last tuesday",
                      "third-to-last wednesday",
                      "third-to-last thursday",
                      "third-to-last friday",
                      "third-to-last saturday",
                      "fourth-to-last sunday",
                      "fourth-to-last monday",
                      "fourth-to-last tuesday",
                      "fourth-to-last wednesday",
                      "fourth-to-last thursday",
                      "fourth-to-last friday",
                      "fourth-to-last saturday",
                      "fifth-to-last sunday",
                      "fifth-to-last monday",
                      "fifth-to-last tuesday",
                      "fifth-to-last wednesday",
                      "fifth-to-last thursday",
                      "fifth-to-last friday",
                      "fifth-to-last saturday"
                    ],
                    "type": "string"
                  },
                  "type": "array"
                },
                "daysOfTheYear": {
                  "description": "Days of the year the reminder repeats on; nonzero, with negatives counting from the end",
                  "items": {
                    "maximum": 366,
                    "minimum": -366,
                    "type": "integer"
                  },
                  "type": "array"
                },
                "end": {
                  "additionalProperties": false,
                  "description": "End condition; omit to repeat indefinitely. Pass date or count, not both.",
                  "properties": {
                    "count": {
                      "description": "Total number of occurrences",
                      "minimum": 1,
                      "type": "integer"
                    },
                    "date": {
                      "description": "Date of the last occurrence (inclusive; a date-only value includes that whole day)",
                      "format": "date-time",
                      "type": "string"
                    }
                  },
                  "type": "object"
                },
                "frequency": {
                  "description": "How often the reminder repeats",
                  "enum": [
                    "daily",
                    "weekly",
                    "monthly",
                    "yearly"
                  ],
                  "type": "string"
                },
                "interval": {
                  "default": 1,
                  "description": "Repeat every N units of the frequency",
                  "minimum": 1,
                  "type": "integer"
                },
                "monthsOfTheYear": {
                  "description": "Months the reminder repeats in",
                  "items": {
                    "enum": [
                      "january",
                      "february",
                      "march",
                      "april",
                      "may",
                      "june",
                      "july",
                      "august",
                      "september",
                      "october",
                      "november",
                      "december"
                    ],
                    "type": "string"
                  },
                  "type": "array"
                },
                "setPositions": {
                  "description": "Which of the matched occurrences to keep; nonzero, e.g. -1 for the last one of each period",
                  "items": {
                    "maximum": 366,
                    "minimum": -366,
                    "type": "integer"
                  },
                  "type": "array"
                },
                "weeksOfTheYear": {
                  "description": "Weeks of the year the reminder repeats in; nonzero, with negatives counting from the end",
                  "items": {
                    "maximum": 53,
                    "minimum": -53,
                    "type": "integer"
                  },
                  "type": "array"
                }
              },
              "required": [
                "frequency"
              ],
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        },
        "start": {
          "anyOf": [
            {
              "description": "Start date/time for the reminder. If timezone is omitted, local time is assumed. Date-only uses local midnight. Pass null to clear.",
              "format": "date-time",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "title": {
          "type": "string"
        },
        "url": {
          "anyOf": [
            {
              "description": "URL attached to the reminder. Pass null to clear.",
              "format": "uri",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "title"
      ],
      "type": "object"
    },
    "name": "reminders_create"
  },
  {
    "description": "Delete a reminder by identifier",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "identifier": {
          "description": "Identifier of the reminder to delete",
          "type": "string"
        }
      },
      "required": [
        "identifier"
      ],
      "type": "object"
    },
    "name": "reminders_delete"
  },
  {
    "description": "Get reminders from the reminders app with flexible filtering options",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "completed": {
          "description": "If true, fetch completed reminders; if false, fetch incomplete; if omitted, fetch all",
          "type": "boolean"
        },
        "end": {
          "description": "End date/time range for fetching reminders. If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "lists": {
          "description": "Names of reminder lists to fetch from; if empty, fetches from all lists",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "query": {
          "description": "Text to search for in reminder titles",
          "type": "string"
        },
        "start": {
          "description": "Start date/time range for fetching reminders. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "reminders_fetch"
  },
  {
    "description": "List available reminder lists",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "reminders_lists"
  },
  {
    "description": "Create a new reminder list",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "title": {
          "description": "Title of the new reminder list",
          "type": "string"
        }
      },
      "required": [
        "title"
      ],
      "type": "object"
    },
    "name": "reminders_lists_create"
  },
  {
    "description": "Delete a reminder list and every reminder it contains. This cannot be undone. Either identifier or name is required.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "identifier": {
          "description": "Identifier of the reminder list to delete, as returned by reminders_lists (preferred)",
          "type": "string"
        },
        "name": {
          "description": "Name of the reminder list to delete, used when identifier is omitted",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "reminders_lists_delete"
  },
  {
    "description": "Rename a reminder list. Either identifier or name is required.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "identifier": {
          "description": "Identifier of the reminder list to rename, as returned by reminders_lists (preferred)",
          "type": "string"
        },
        "name": {
          "description": "Current name of the reminder list, used when identifier is omitted",
          "type": "string"
        },
        "title": {
          "description": "New title for the reminder list",
          "type": "string"
        }
      },
      "required": [
        "title"
      ],
      "type": "object"
    },
    "name": "reminders_lists_rename"
  },
  {
    "description": "Update an existing reminder. Only provide values for properties that need to be changed; omit any properties that should remain unchanged. Pass null to clear an optional property.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "alarms": {
          "anyOf": [
            {
              "description": "Alarm configurations for the reminder. Pass null to remove all alarms.",
              "items": {
                "anyOf": [
                  {
                    "description": "Minutes before the due date",
                    "type": "integer"
                  },
                  {
                    "additionalProperties": false,
                    "properties": {
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "minutes": {
                        "description": "Minutes offset from the due date (positive is before)",
                        "type": "integer"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "relative",
                        "type": "string"
                      }
                    },
                    "required": [
                      "minutes"
                    ],
                    "type": "object"
                  },
                  {
                    "additionalProperties": false,
                    "properties": {
                      "datetime": {
                        "description": "Alarm date/time. If timezone is omitted, local time is assumed.",
                        "format": "date-time",
                        "type": "string"
                      },
                      "emailAddress": {
                        "description": "Email address to send notification to",
                        "type": "string"
                      },
                      "sound": {
                        "description": "Sound name to play when alarm triggers",
                        "enum": [
                          "Basso",
                          "Blow",
                          "Bottle",
                          "Frog",
                          "Funk",
                          "Glass",
                          "Hero",
                          "Morse",
                          "Ping",
                          "Pop",
                          "Purr",
                          "Sosumi",
                          "Submarine",
                          "Tink"
                        ],
                        "type": "string"
                      },
                      "type": {
                        "const": "absolute",
                        "type": "string"
                      }
                    },
                    "required": [
                      "type",
                      "datetime"
                    ],
                    "type": "object"
                  },
                  {
                    "anyOf": [
                      {
                        "additionalProperties": false,
                        "properties": {
                          "emailAddress": {
                            "description": "Email address to send notification to",
                            "type": "string"
                          },
                          "location": {
                            "description": "Place name or address to trigger on, resolved with Maps",
                            "type": "string"
                          },
                          "proximity": {
                            "default": "enter",
                            "description": "Proximity trigger type",
                            "enum": [
                              "enter",
                              "leave"
                            ],
                            "type": "string"
                          },
                          "radius": {
                            "description": "Radius in meters. Omit to use the system default.",
                            "minimum": 0,
                            "type": "number"
                          },
                          "sound": {
                            "description": "Sound name to play when alarm triggers",
                            "enum": [
                              "Basso",
                              "Blow",
                              "Bottle",
                              "Frog",
                              "Funk",
                              "Glass",
                              "Hero",
                              "Morse",
                              "Ping",
                              "Pop",
                              "Purr",
                              "Sosumi",
                              "Submarine",
                              "Tink"
                            ],
                            "type": "string"
                          },
                          "type": {
                            "const": "proximity",
                            "type": "string"
                          }
                        },
                        "required": [
                          "type",
                          "location"
                        ],
                        "type": "object"
                      },
                      {
                        "additionalProperties": false,
                        "properties": {
                          "emailAddress": {
                            "description": "Email address to send notification to",
                            "type": "string"
                          },
                          "latitude": {
                            "maximum": 90,
                            "minimum": -90,
                            "type": "number"
                          },
                          "locationTitle": {
                            "type": "string"
                          },
                          "longitude": {
                            "maximum": 180,
                            "minimum": -180,
                            "type": "number"
                          },
                          "proximity": {
                            "default": "enter",
                            "description": "Proximity trigger type",
                            "enum": [
                              "enter",
                              "leave"
                            ],
                            "type": "string"
                          },
                          "radius": {
                            "description": "Radius in meters. Omit to use the system default.",
                            "minimum": 0,
                            "type": "number"
                          },
                          "sound": {
                            "description": "Sound name to play when alarm triggers",
                            "enum": [
                              "Basso",
                              "Blow",
                              "Bottle",
                              "Frog",
                              "Funk",
                              "Glass",
                              "Hero",
                              "Morse",
                              "Ping",
                              "Pop",
                              "Purr",
                              "Sosumi",
                              "Submarine",
                              "Tink"
                            ],
                            "type": "string"
                          },
                          "type": {
                            "const": "proximity",
                            "type": "string"
                          }
                        },
                        "required": [
                          "type",
                          "locationTitle",
                          "latitude",
                          "longitude"
                        ],
                        "type": "object"
                      }
                    ]
                  }
                ]
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ]
        },
        "completed": {
          "description": "Completion state. Setting true records completion at the current time and advances recurring reminders; false clears the completion date.",
          "type": "boolean"
        },
        "due": {
          "anyOf": [
            {
              "description": "Due date/time for the reminder. If timezone is omitted, local time is assumed. Date-only uses local midnight. Pass null to clear.",
              "format": "date-time",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "identifier": {
          "description": "Identifier of the reminder to update, as returned by reminders_fetch or reminders_create",
          "type": "string"
        },
        "list": {
          "description": "Reminder list name, or the identifier of one of several lists sharing a name. Must match an existing list.",
          "type": "string"
        },
        "notes": {
          "anyOf": [
            {
              "description": "Notes for the reminder. Pass null to clear.",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "priority": {
          "description": "Priority; omit to leave unchanged",
          "enum": [
            "none",
            "low",
            "medium",
            "high"
          ],
          "type": "string"
        },
        "recurrence": {
          "anyOf": [
            {
              "additionalProperties": false,
              "description": "Recurrence rule for a repeating reminder. Pass null to stop repeating.",
              "properties": {
                "daysOfTheMonth": {
                  "description": "Days of the month the reminder repeats on; nonzero, with negatives counting from the end (-1 is the last day)",
                  "items": {
                    "maximum": 31,
                    "minimum": -31,
                    "type": "integer"
                  },
                  "type": "array"
                },
                "daysOfTheWeek": {
                  "description": "Days of the week the reminder repeats on; prefix an ordinal (first through fifth, last, or second-to-last through fifth-to-last) to repeat on one weekday of the month, e.g. \"second tuesday\"",
                  "items": {
                    "enum": [
                      "sunday",
                      "monday",
                      "tuesday",
                      "wednesday",
                      "thursday",
                      "friday",
                      "saturday",
                      "first sunday",
                      "first monday",
                      "first tuesday",
                      "first wednesday",
                      "first thursday",
                      "first friday",
                      "first saturday",
                      "second sunday",
                      "second monday",
                      "second tuesday",
                      "second wednesday",
                      "second thursday",
                      "second friday",
                      "second saturday",
                      "third sunday",
                      "third monday",
                      "third tuesday",
                      "third wednesday",
                      "third thursday",
                      "third friday",
                      "third saturday",
                      "fourth sunday",
                      "fourth monday",
                      "fourth tuesday",
                      "fourth wednesday",
                      "fourth thursday",
                      "fourth friday",
                      "fourth saturday",
                      "fifth sunday",
                      "fifth monday",
                      "fifth tuesday",
                      "fifth wednesday",
                      "fifth thursday",
                      "fifth friday",
                      "fifth saturday",
                      "last sunday",
                      "last monday",
                      "last tuesday",
                      "last wednesday",
                      "last thursday",
                      "last friday",
                      "last saturday",
                      "second-to-last sunday",
                      "second-to-last monday",
                      "second-to-last tuesday",
                      "second-to-last wednesday",
                      "second-to-last thursday",
                      "second-to-last friday",
                      "second-to-last saturday",
                      "third-to-last sunday",
                      "third-to-last monday",
                      "third-to-last tuesday",
                      "third-to-last wednesday",
                      "third-to-last thursday",
                      "third-to-last friday",
                      "third-to-last saturday",
                      "fourth-to-last sunday",
                      "fourth-to-last monday",
                      "fourth-to-last tuesday",
                      "fourth-to-last wednesday",
                      "fourth-to-last thursday",
                      "fourth-to-last friday",
                      "fourth-to-last saturday",
                      "fifth-to-last sunday",
                      "fifth-to-last monday",
                      "fifth-to-last tuesday",
                      "fifth-to-last wednesday",
                      "fifth-to-last thursday",
                      "fifth-to-last friday",
                      "fifth-to-last saturday"
                    ],
                    "type": "string"
                  },
                  "type": "array"
                },
                "daysOfTheYear": {
                  "description": "Days of the year the reminder repeats on; nonzero, with negatives counting from the end",
                  "items": {
                    "maximum": 366,
                    "minimum": -366,
                    "type": "integer"
                  },
                  "type": "array"
                },
                "end": {
                  "additionalProperties": false,
                  "description": "End condition; omit to repeat indefinitely. Pass date or count, not both.",
                  "properties": {
                    "count": {
                      "description": "Total number of occurrences",
                      "minimum": 1,
                      "type": "integer"
                    },
                    "date": {
                      "description": "Date of the last occurrence (inclusive; a date-only value includes that whole day)",
                      "format": "date-time",
                      "type": "string"
                    }
                  },
                  "type": "object"
                },
                "frequency": {
                  "description": "How often the reminder repeats",
                  "enum": [
                    "daily",
                    "weekly",
                    "monthly",
                    "yearly"
                  ],
                  "type": "string"
                },
                "interval": {
                  "default": 1,
                  "description": "Repeat every N units of the frequency",
                  "minimum": 1,
                  "type": "integer"
                },
                "monthsOfTheYear": {
                  "description": "Months the reminder repeats in",
                  "items": {
                    "enum": [
                      "january",
                      "february",
                      "march",
                      "april",
                      "may",
                      "june",
                      "july",
                      "august",
                      "september",
                      "october",
                      "november",
                      "december"
                    ],
                    "type": "string"
                  },
                  "type": "array"
                },
                "setPositions": {
                  "description": "Which of the matched occurrences to keep; nonzero, e.g. -1 for the last one of each period",
                  "items": {
                    "maximum": 366,
                    "minimum": -366,
                    "type": "integer"
                  },
                  "type": "array"
                },
                "weeksOfTheYear": {
                  "description": "Weeks of the year the reminder repeats in; nonzero, with negatives counting from the end",
                  "items": {
                    "maximum": 53,
                    "minimum": -53,
                    "type": "integer"
                  },
                  "type": "array"
                }
              },
              "required": [
                "frequency"
              ],
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        },
        "start": {
          "anyOf": [
            {
              "description": "Start date/time for the reminder. If timezone is omitted, local time is assumed. Date-only uses local midnight. Pass null to clear.",
              "format": "date-time",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "title": {
          "type": "string"
        },
        "url": {
          "anyOf": [
            {
              "description": "URL attached to the reminder. Pass null to clear.",
              "format": "uri",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "identifier"
      ],
      "type": "object"
    },
    "name": "reminders_update"
  },
  {
    "description": "Create a room.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        },
        "name": {
          "type": "string"
        }
      },
      "required": [
        "name"
      ],
      "type": "object"
    },
    "name": "rooms_create"
  },
  {
    "description": "List rooms and identify the Default Room.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "rooms_list"
  },
  {
    "description": "Remove a room. Its accessories return to the Default Room.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "room": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "room"
      ],
      "type": "object"
    },
    "name": "rooms_remove"
  },
  {
    "description": "Rename a room.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "name": {
          "type": "string"
        },
        "room": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "room",
        "name"
      ],
      "type": "object"
    },
    "name": "rooms_rename"
  },
  {
    "description": "Create a scene with characteristic write actions.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "actions": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "characteristic": {
                "description": "HomeKit uniqueIdentifier UUID",
                "type": "string"
              },
              "value": {
                "anyOf": [
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number"
                  },
                  {
                    "type": "string"
                  }
                ]
              }
            },
            "required": [
              "characteristic",
              "value"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        },
        "name": {
          "type": "string"
        }
      },
      "required": [
        "name",
        "actions"
      ],
      "type": "object"
    },
    "name": "scenes_create"
  },
  {
    "description": "Execute a scene and change its devices.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "scene": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "scene"
      ],
      "type": "object"
    },
    "name": "scenes_execute"
  },
  {
    "description": "List scenes with resolved characteristic actions.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "scenes_list"
  },
  {
    "description": "Remove a scene from the home.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "scene": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "scene"
      ],
      "type": "object"
    },
    "name": "scenes_remove"
  },
  {
    "description": "Rename a scene, set characteristic actions, or remove actions.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "add_actions": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "characteristic": {
                "description": "HomeKit uniqueIdentifier UUID",
                "type": "string"
              },
              "value": {
                "anyOf": [
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number"
                  },
                  {
                    "type": "string"
                  }
                ]
              }
            },
            "required": [
              "characteristic",
              "value"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "name": {
          "type": "string"
        },
        "remove_characteristics": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        },
        "scene": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "scene"
      ],
      "type": "object"
    },
    "name": "scenes_update"
  },
  {
    "description": "Rename a service within an accessory.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "name": {
          "type": "string"
        },
        "service": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "service",
        "name"
      ],
      "type": "object"
    },
    "name": "services_rename"
  },
  {
    "description": "List all available shortcuts on this Mac",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    },
    "name": "shortcuts_list"
  },
  {
    "description": "Run a shortcut by name, optionally with text input",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "input": {
          "description": "Optional text input to pass to the shortcut",
          "type": "string"
        },
        "name": {
          "description": "The name of the shortcut to run",
          "type": "string"
        }
      },
      "required": [
        "name"
      ],
      "type": "object"
    },
    "name": "shortcuts_run"
  },
  {
    "description": "Play a system sound",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "sound": {
          "default": "Sosumi",
          "enum": [
            "Basso",
            "Blow",
            "Bottle",
            "Frog",
            "Funk",
            "Glass",
            "Hero",
            "Morse",
            "Ping",
            "Pop",
            "Purr",
            "Sosumi",
            "Submarine",
            "Tink"
          ],
          "type": "string"
        }
      },
      "required": [
        "sound"
      ],
      "type": "object"
    },
    "name": "utilities_beep"
  },
  {
    "description": "Fetch the audio of a Voice Memos recording",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "description": "Identifier of the recording, as returned by voice_memos_fetch",
          "type": "string"
        },
        "maxBytes": {
          "default": 25,
          "description": "Refuse audio files larger than this",
          "maximum": 100,
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "voice_memo_audio_fetch"
  },
  {
    "description": "Fetch the transcript that Voice Memos made of a recording",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "description": "Identifier of the recording, as returned by voice_memos_fetch",
          "type": "string"
        },
        "timestamps": {
          "default": false,
          "description": "Include each transcribed word with its start and end time in seconds",
          "type": "boolean"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "voice_memo_transcript_fetch"
  },
  {
    "description": "Fetch recordings from Voice Memos, newest first, with their titles, folders, and durations",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "cursor": {
          "description": "The nextCursor value from a previous voice_memos_fetch, to fetch the next page",
          "type": "string"
        },
        "end": {
          "description": "End of the date range (exclusive). ISO 8601 format. If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "folder": {
          "description": "Name of a Voice Memos folder to read (case-insensitive)",
          "type": "string"
        },
        "limit": {
          "default": 30,
          "description": "Maximum recordings to return",
          "minimum": 1,
          "type": "integer"
        },
        "query": {
          "description": "Text to match in recording titles, ignoring case and diacritics",
          "type": "string"
        },
        "recentlyDeleted": {
          "default": false,
          "description": "Fetch recordings from Recently Deleted instead of the library",
          "type": "boolean"
        },
        "start": {
          "description": "Start of the date range (inclusive). ISO 8601 format. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "voice_memos_fetch"
  },
  {
    "description": "Fetch the audio of a voicemail (carrier voicemails and FaceTime audio messages)",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "description": "Identifier of the voicemail, as returned by voicemails_fetch",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "voicemail_audio_fetch"
  },
  {
    "description": "Fetch the transcript of a voicemail",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "description": "Identifier of the voicemail, as returned by voicemails_fetch",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    },
    "name": "voicemail_transcript_fetch"
  },
  {
    "description": "Fetch voicemails from the Mac (synced from iPhone, including FaceTime messages), newest first, from the inbox unless another mailbox is requested",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "end": {
          "description": "End of the date range (exclusive). ISO 8601 format. If timezone is omitted, local time is assumed. A date-only value includes that whole day.",
          "format": "date-time",
          "type": "string"
        },
        "limit": {
          "default": 30,
          "description": "Maximum voicemails to return",
          "minimum": 1,
          "type": "integer"
        },
        "mailbox": {
          "default": "inbox",
          "description": "Voicemail mailbox to read: the inbox, blocked or deleted messages, or all of them",
          "enum": [
            "inbox",
            "blocked",
            "deleted",
            "all"
          ],
          "type": "string"
        },
        "sender": {
          "description": "Phone number or address to filter by (partial match supported; phone numbers match by digits, ignoring formatting)",
          "type": "string"
        },
        "start": {
          "description": "Start of the date range (inclusive). ISO 8601 format. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "type": {
          "description": "Filter by message type, or omit for all",
          "enum": [
            "carrierVoicemail",
            "faceTimeAudio",
            "faceTimeVideo"
          ],
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "voicemails_fetch"
  },
  {
    "description": "Get current weather for a location",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "latitude": {
          "type": "number"
        },
        "longitude": {
          "type": "number"
        }
      },
      "required": [
        "latitude",
        "longitude"
      ],
      "type": "object"
    },
    "name": "weather_current"
  },
  {
    "description": "Get daily weather forecast for a location",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "days": {
          "default": 7,
          "description": "Number of forecast days (max 10)",
          "maximum": 10,
          "minimum": 1,
          "type": "integer"
        },
        "latitude": {
          "type": "number"
        },
        "longitude": {
          "type": "number"
        }
      },
      "required": [
        "latitude",
        "longitude"
      ],
      "type": "object"
    },
    "name": "weather_daily"
  },
  {
    "description": "Get hourly weather forecast for a location",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "hours": {
          "default": 24,
          "description": "Number of hours to forecast",
          "maximum": 240,
          "minimum": 1,
          "type": "integer"
        },
        "latitude": {
          "type": "number"
        },
        "longitude": {
          "type": "number"
        }
      },
      "required": [
        "latitude",
        "longitude"
      ],
      "type": "object"
    },
    "name": "weather_hourly"
  },
  {
    "description": "Get minute-by-minute weather forecast for a location",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "latitude": {
          "type": "number"
        },
        "longitude": {
          "type": "number"
        },
        "minutes": {
          "default": 60,
          "description": "Number of minutes to forecast",
          "maximum": 120,
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "latitude",
        "longitude"
      ],
      "type": "object"
    },
    "name": "weather_minute"
  },
  {
    "description": "Create a zone with optional rooms.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        },
        "name": {
          "type": "string"
        },
        "rooms": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "name"
      ],
      "type": "object"
    },
    "name": "zones_create"
  },
  {
    "description": "List zones and their room IDs.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "home": {
          "description": "Home UUID. Required when more than one home exists.",
          "type": "string"
        }
      },
      "type": "object"
    },
    "name": "zones_list"
  },
  {
    "description": "Remove a zone without removing its rooms.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "zone": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "zone"
      ],
      "type": "object"
    },
    "name": "zones_remove"
  },
  {
    "description": "Rename a zone or change its rooms.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "add_rooms": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        },
        "name": {
          "type": "string"
        },
        "remove_rooms": {
          "items": {
            "description": "HomeKit uniqueIdentifier UUID",
            "type": "string"
          },
          "type": "array"
        },
        "zone": {
          "description": "HomeKit uniqueIdentifier UUID",
          "type": "string"
        }
      },
      "required": [
        "zone"
      ],
      "type": "object"
    },
    "name": "zones_update"
  }
]
```
