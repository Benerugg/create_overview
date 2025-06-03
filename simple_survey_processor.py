#!/usr/bin/env python3

import json
import pandas as pd
import pyreadstat
from typing import Dict, Any, List
import numpy as np
import requests
import os
import sys
from pathlib import Path

def get_downloads_folder():
    """Get the Downloads folder path for the current OS."""
    home = Path.home()
    return home / "Downloads"

def download_survey_data(survey_id: str, token: str, output_dir: Path) -> tuple[Dict, List]:
    """Download survey structure and responses from API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    # Create output directory if it doesn't exist
    survey_dir = output_dir / f"survey_{survey_id}"
    survey_dir.mkdir(exist_ok=True)
    
    # Download survey structure
    print(f"Downloading survey structure for survey {survey_id}...")
    survey_url = f"https://backend.workey.ai/surveys/{survey_id}"
    try:
        survey_response = requests.get(survey_url, headers=headers)
        survey_response.raise_for_status()
        survey_data = survey_response.json()
        
        # Save survey data
        survey_path = survey_dir / "survey.json"
        with open(survey_path, 'w', encoding='utf-8') as f:
            json.dump(survey_data, f, ensure_ascii=False, indent=2)
        print(f"✓ Survey structure saved to: {survey_path}")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading survey structure: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Download responses
    print(f"Downloading responses for survey {survey_id}...")
    replies_url = f"https://backend.workey.ai/surveys/replies/{survey_id}"
    try:
        replies_response = requests.get(replies_url, headers=headers)
        replies_response.raise_for_status()
        replies_data = replies_response.json()
        
        # Save replies data
        replies_path = survey_dir / "replies.json"
        with open(replies_path, 'w', encoding='utf-8') as f:
            json.dump(replies_data, f, ensure_ascii=False, indent=2)
        print(f"✓ Responses saved to: {replies_path}")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading responses: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    return survey_data, replies_data, survey_dir

def create_question_mapping(survey_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Create mappings for all question types from the survey structure."""
    questions = {}
    id_to_key = {}
    value_labels = {}
    choice_to_key = {}  # Mapping for choice IDs to question keys
    measurement_types = {}  # New dict for measurement types
    
    for page in survey_data['pages']:
        for element in page['elements']:
            if element.get('itemKey'):
                # Set measurement type based on element type
                if element['@type'] == 'Number':
                    measurement_types[element['itemKey']] = 'Scale'
                else:
                    measurement_types[element['itemKey']] = 'Nominal'
                    
            if element['@type'] == 'Matrix':
                # Handle Matrix questions
                col_labels = {
                    int(col['value']): col['text']['default']
                    for col in element['columns']
                    if col.get('value') is not None
                }
                
                for row in element['rows']:
                    if row.get('itemKey'):
                        questions[row['itemKey']] = {
                            'type': 'Matrix',
                            'text': row['text']['default'],
                            'id': row['id']
                        }
                        id_to_key[str(row['id'])] = row['itemKey']
                        if col_labels:
                            value_labels[row['itemKey']] = col_labels
                            
            elif element['@type'] == 'Radiogroup':
                if element.get('itemKey'):
                    item_key = element['itemKey']
                    questions[item_key] = {
                        'type': 'Radiogroup',
                        'text': element['title']['default'],
                        'id': element['id']
                    }
                    id_to_key[str(element['id'])] = item_key
                    
                    # Create value labels and choice mapping
                    radio_labels = {}
                    for choice in element['choices']:
                        if choice.get('value') is not None:
                            value = int(choice['value'])
                            radio_labels[value] = choice['text']['default']
                            choice_to_key[str(choice['id'])] = item_key
                    
                    if radio_labels:
                        value_labels[item_key] = radio_labels
                    
            elif element['@type'] == 'Number':
                if element.get('itemKey'):
                    questions[element['itemKey']] = {
                        'type': 'Number',
                        'text': element['title']['default'],
                        'id': element['id'],
                        'min': element.get('min'),
                        'max': element.get('max')
                    }
                    id_to_key[str(element['id'])] = element['itemKey']
    
    return {
        'questions': questions,
        'id_to_key': id_to_key,
        'value_labels': value_labels,
        'choice_to_key': choice_to_key,
        'measurement_types': measurement_types  # Include measurement types in return
    }

def process_responses(responses_data: List[Dict[str, Any]], mappings: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """Process responses using the mappings created from survey structure."""
    processed_responses = []
    
    for response in responses_data:
        # Initialize response dict
        processed = {
            'response_id': response['id'],
            'created_at': response.get('createdAt', None)
        }
        
        # Initialize all questions with -999
        all_questions = {key: -999 for key in mappings['questions'].keys()}
        processed.update(all_questions)
        
        # Process each answer
        for answer in response.get('answers', []):
            question_key = None
            value = None
            
            if answer['@type'] == 'matrix':
                row_id = str(answer['row_id'])
                question_key = mappings['id_to_key'].get(row_id)
                value = answer.get('value')
                
            elif answer['@type'] == 'choice':
                choice_id = str(answer.get('choice_id'))
                question_key = mappings['choice_to_key'].get(choice_id)
                value = answer.get('value')
                
            elif answer['@type'] == 'number':
                element_id = str(answer['element_id'])
                question_key = mappings['id_to_key'].get(element_id)
                value = answer.get('value')
            
            # Update processed response if we have valid data
            if question_key is not None and value is not None:
                processed[question_key] = value
        
        processed_responses.append(processed)
    
    return pd.DataFrame(processed_responses)

def main():
    print("=" * 60)
    print("WORKEY SURVEY DATA PROCESSOR")
    print("=" * 60)
    print("\nThis tool will download and process survey data from Workey.")
    print("You will need:")
    print("  1. Your Survey ID (e.g., 10551)")
    print("  2. Your API Token")
    print("\n" + "=" * 60 + "\n")
    
    # Get user input
    survey_id = input("Enter Survey ID: ").strip()
    if not survey_id:
        print("Error: Survey ID cannot be empty!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    token = input("Enter API Token: ").strip()
    if not token:
        print("Error: Token cannot be empty!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Get Downloads folder
    downloads_dir = get_downloads_folder()
    
    print(f"\n🚀 Starting Survey Data Processing")
    print(f"=" * 50)
    print(f"Survey ID: {survey_id}")
    print(f"Output directory: {downloads_dir}")
    print(f"=" * 50 + "\n")
    
    # Download data
    survey_data, responses_data, output_dir = download_survey_data(
        survey_id, 
        token, 
        downloads_dir
    )
    
    print("\n📊 Processing survey data...")
    
    # Create mappings
    mappings = create_question_mapping(survey_data)
    
    # Process responses
    df = process_responses(responses_data, mappings)
    
    # Create column labels for SPSS
    column_labels = {
        key: qdef['text']
        for key, qdef in mappings['questions'].items()
    }
    
    # Convert all columns to numeric, replacing any remaining None with -999
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-999).astype(int)
    
    # Print summary info
    print(f"\n📈 Data Summary:")
    print(f"  - Total responses: {len(df)}")
    print(f"  - Total questions: {len(mappings['questions'])}")
    print(f"  - Data shape: {df.shape}")
    
    # Export to CSV
    csv_path = output_dir / f"survey_{survey_id}_responses.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n✓ CSV exported to: {csv_path}")
    
    # Create measurement info for SPSS
    measurement_info = {}
    for col in df.columns:
        if col in mappings['measurement_types']:
            measurement_info[col] = 'scale' if mappings['measurement_types'][col] == 'Scale' else 'nominal'
        else:
            measurement_info[col] = 'nominal'  # Default to nominal for non-mapped columns
    
    # Export to SPSS
    spss_path = output_dir / f"survey_{survey_id}.sav"
    pyreadstat.write_sav(
        df,
        str(spss_path),  # pyreadstat needs string path
        column_labels=column_labels,
        variable_value_labels=mappings['value_labels'],
        variable_measure=measurement_info
    )
    print(f"✓ SPSS file exported to: {spss_path}")
    
    # Save metadata
    metadata = {
        'survey_id': survey_id,
        'total_responses': len(df),
        'total_questions': len(mappings['questions']),
        'questions': mappings['questions'],
        'measurement_types': mappings['measurement_types'],
        'value_labels': mappings['value_labels']
    }
    
    metadata_path = output_dir / f"survey_{survey_id}_metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"✓ Metadata saved to: {metadata_path}")
    
    print(f"\n✨ Processing complete! All files saved to:")
    print(f"   {output_dir}")
    print(f"\nFiles created:")
    print(f"  - survey.json (raw survey structure)")
    print(f"  - replies.json (raw responses)")
    print(f"  - survey_{survey_id}_responses.csv (processed data)")
    print(f"  - survey_{survey_id}.sav (SPSS file)")
    print(f"  - survey_{survey_id}_metadata.json (variable info)")
    
    print("\n" + "=" * 60)
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()