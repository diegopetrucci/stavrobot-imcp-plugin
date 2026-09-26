# iMCP tools

Captured from iMCP **1.6.0** on **2026-09-26** using a read-only MCP handshake and `tools/list`.

The generic full iMCP 1.6.0 tool surface when all services are enabled is documented below; this is not a record of the operator's Mac configuration.

If the live bridge allowlist uses `*`, this surface can grow when iMCP adds a
tool without any allowlist edit. Treat every upgrade as requiring a fresh
`tools/list` review and explicit approval of the expanded read/write surface;
this document does not alter the live allowlist.

Only tool names, descriptions, and input schemas are recorded below. No tool was invoked and no tool result or personal data was captured.

```json
[
  {
    "name": "calendars_list",
    "description": "List available calendars",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    }
  },
  {
    "name": "events_fetch",
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
          "description": "End date/time (defaults to one week from start; one day if start is date-only). If timezone is omitted, local time is assumed.",
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
    }
  },
  {
    "name": "events_create",
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
                    "description": "Minutes offset from event start (negative for before, positive for after)",
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
                    "type": "number"
                  },
                  "locationTitle": {
                    "type": "string"
                  },
                  "longitude": {
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
                    "default": 200,
                    "description": "Radius in meters",
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
    }
  },
  {
    "name": "events_delete",
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
    }
  },
  {
    "name": "capture_take_picture",
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
    }
  },
  {
    "name": "capture_record_audio",
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
    }
  },
  {
    "name": "capture_take_screenshot",
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
    }
  },
  {
    "name": "contacts_me",
    "description": "Get contact information about the user, including name, phone number, email, birthday, relations, address, online presence, and occupation. Always run this tool when the user asks a question that requires personal information about themselves.",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    }
  },
  {
    "name": "contacts_search",
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
    }
  },
  {
    "name": "contacts_list",
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
    }
  },
  {
    "name": "contacts_update",
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
    }
  },
  {
    "name": "contacts_create",
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
    }
  },
  {
    "name": "location_current",
    "description": "Get the user's current location",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    }
  },
  {
    "name": "location_geocode",
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
    }
  },
  {
    "name": "location_reverse-geocode",
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
    }
  },
  {
    "name": "maps_search",
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
    }
  },
  {
    "name": "maps_directions",
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
    }
  },
  {
    "name": "maps_explore",
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
    }
  },
  {
    "name": "maps_eta",
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
    }
  },
  {
    "name": "maps_generate",
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
    }
  },
  {
    "name": "messages_fetch",
    "description": "Fetch messages from the Messages app. Each message names the conversation it belongs to (isPartOf), with its participants.",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "attachments": {
          "default": false,
          "description": "List each message's attachments (attachment: name, encodingFormat, contentSize, @id) and include messages that carry attachments but no text",
          "type": "boolean"
        },
        "end": {
          "description": "End of the date range (exclusive). If timezone is omitted, local time is assumed. Date-only uses local midnight.",
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
    }
  },
  {
    "name": "reminders_lists",
    "description": "List available reminder lists",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    }
  },
  {
    "name": "reminders_fetch",
    "description": "Get reminders from the reminders app with flexible filtering options",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "completed": {
          "description": "If true, fetch completed reminders; if false, fetch incomplete; if omitted, fetch all",
          "type": "boolean"
        },
        "end": {
          "description": "End date/time range for fetching reminders. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
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
    }
  },
  {
    "name": "reminders_create",
    "description": "Create a new reminder with specified properties",
    "inputSchema": {
      "additionalProperties": false,
      "properties": {
        "alarms": {
          "description": "Minutes before due date to set alarms",
          "items": {
            "type": "integer"
          },
          "type": "array"
        },
        "due": {
          "description": "Due date/time for the reminder. If timezone is omitted, local time is assumed. Date-only uses local midnight.",
          "format": "date-time",
          "type": "string"
        },
        "list": {
          "description": "Reminder list name (uses default if not specified)",
          "type": "string"
        },
        "notes": {
          "type": "string"
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
        "title": {
          "type": "string"
        }
      },
      "required": [
        "title"
      ],
      "type": "object"
    }
  },
  {
    "name": "shortcuts_list",
    "description": "List all available shortcuts on this Mac",
    "inputSchema": {
      "additionalProperties": false,
      "type": "object"
    }
  },
  {
    "name": "shortcuts_run",
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
    }
  },
  {
    "name": "weather_current",
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
    }
  },
  {
    "name": "weather_daily",
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
    }
  },
  {
    "name": "weather_hourly",
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
    }
  },
  {
    "name": "weather_minute",
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
    }
  }
]
```
