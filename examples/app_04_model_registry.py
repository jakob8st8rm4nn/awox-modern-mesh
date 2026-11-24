"""Look up APK model names, advertisement codes and descriptor properties.

This example runs offline. MODEL_LOOKUP_CODE and MODEL_NAME are independent
lookup inputs. A code can match several names; a descriptor entry alone does
not establish that every physical device implements its listed properties.
"""

from awox import lookup_model, lookup_models_by_code, lookup_model_properties

# Change these two independent lookup inputs to inspect other APK entries.
# Use model_lookup_code from a parsed advertisement, not the raw model_code.
MODEL_LOOKUP_CODE = bytes.fromhex("2096")  # Parsed advertisement model lookup code
MODEL_NAME = "EGLO-ZM-RGB-TW"  # Independent model-name lookup


def main():
    models = lookup_models_by_code(MODEL_LOOKUP_CODE)
    print("Scanner model lookup code:", MODEL_LOOKUP_CODE.hex())
    if not models:
        print("No exact APK model match for this code.")
    else:
        print("APK model names for code:")
        for model in models:
            print(f"  {model.name} (protocol: {model.protocol})")

    # Name lookup is independent of the lookup by model code above.
    model = lookup_model(MODEL_NAME)
    print("\nRequested model name:", MODEL_NAME)
    if model is None:
        print("This model name is not in the analyzed APK register.")
        return

    print("Registered model:", model.name)
    print("Protocol family:", model.protocol)
    properties = lookup_model_properties(model.name)
    if properties is None:
        print("No APK descriptor properties found.")
        return
    print("APK descriptor properties:")
    for property_name in properties:
        print(" -", property_name)
    print("Note: APK properties are not verified physical device capabilities.")


if __name__ == "__main__":
    main()
